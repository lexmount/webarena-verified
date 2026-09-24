"""NetworkEventEvaluator for validating network request details.

This evaluator validates network events by checking URL, headers, query parameters,
and response status against expected criteria using four-step architecture.
"""

import re
from collections.abc import Mapping
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlsplit

from webarena_verified.core.evaluation.data_types import URL
from webarena_verified.core.utils import logger
from webarena_verified.core.utils.jsonpath_utils import extract_jsonpath_value, is_jsonpath_key
from webarena_verified.types.eval import EvalAssertion, EvalStatus, EvaluatorResult, TaskEvalContext
from webarena_verified.types.task import NetworkEventEvaluatorCfg, NetworkEventSpec
from webarena_verified.types.tracing import NetworkEvent

from .base import BaseEvaluator

if TYPE_CHECKING:
    from webarena_verified.types.common import SerializableMappingProxyType


_PLACEHOLDER = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def _template_match(template: str, actual: Any, bindings: dict[str, str]) -> bool:
    """Match a dynamic evaluator template and consistently bind its names."""
    if not isinstance(actual, (str, int, float)):
        return False
    cursor = 0
    parts = ["^"]
    local_groups: set[str] = set()
    for match in _PLACEHOLDER.finditer(template):
        parts.append(re.escape(template[cursor : match.start()]))
        name = match.group(1)
        if name in bindings:
            parts.append(re.escape(bindings[name]))
        elif name in local_groups:
            parts.append(f"(?P={name})")
        else:
            parts.append(f"(?P<{name}>[^/?#&]+)")
            local_groups.add(name)
        cursor = match.end()
    parts.extend((re.escape(template[cursor:]), "$"))
    matched = re.fullmatch("".join(parts), str(actual))
    if matched is None:
        return False
    bindings.update(matched.groupdict())
    return True


def _placeholder_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, Mapping):
        names: set[str] = set()
        for key, item in value.items():
            names.update(_placeholder_names(key))
            names.update(_placeholder_names(item))
        return names
    if isinstance(value, (list, tuple)):
        names = set()
        for item in value:
            names.update(_placeholder_names(item))
        return names
    return set()


def _substitute_placeholders(value: Any, bindings: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda match: bindings[match.group(1)], value)
    if isinstance(value, list):
        return [_substitute_placeholders(item, bindings) for item in value]
    if isinstance(value, tuple):
        return tuple(_substitute_placeholders(item, bindings) for item in value)
    if isinstance(value, Mapping):
        return {
            _substitute_placeholders(key, bindings): _substitute_placeholders(item, bindings)
            for key, item in value.items()
        }
    return value


class NetworkEventEvaluator(BaseEvaluator[NetworkEventEvaluatorCfg]):
    """Validates network events using four-step architecture.

    The evaluator:
    - Searches for network events matching URL and headers criteria
    - Validates all fields in the expected block (url, headers, query_string, response_status, post_data)
    - Supports checking the last matching event or any matching event
    - Respects ignored query parameters during comparison
    - Supports alternatives in expected values

    Architecture:
    - Step 1: Filter and extract event data from network trace
    - Step 2: Get expected event data from config (with alternatives)
    - Step 3: Normalize both using schema-based normalization
    - Step 4: Compare normalized values structurally
    """

    def _get_actual_value(self, context: TaskEvalContext, config: NetworkEventEvaluatorCfg) -> list[NetworkEventSpec]:
        """Extract and navigate to actual value from network events.

        Steps:
        1. Filter network events based on config criteria (URL pattern, method, event_type, headers)
        2. Select event(s) based on config (last event only, or all matching)
        3. Extract relevant data from selected events

        Args:
            context: Task evaluation context
            config: Evaluator configuration

        Returns:
            Raw actual value before normalization (single event data dict or list of event data dicts)
            Returns None if no matching events found

        Raises:
            ValueError: If no events match the criteria
        """
        # Step 1: Filter events based on config criteria (search through all evaluation events)
        matching_events = self._filter_events_by_criteria(context.network_trace.evaluation_events, context, config)

        if not matching_events:
            return []

        # Step 2: Select event(s)
        selected_events = [matching_events[-1]] if config.last_event_only else matching_events

        # Step 3: Extract relevant data from events
        extracted_data = []
        for event in selected_events:
            event_data = self._extract_event_data(event, config, context)
            extracted_data.append(event_data)

        return [extracted_data[0]] if config.last_event_only else extracted_data

    def _get_expected_value(self, config: NetworkEventEvaluatorCfg) -> NetworkEventSpec:
        """Get expected value from config.

        Returns:
            Expected network event data as dict with alternatives support
        """
        return config.expected

    def _normalized_expected_value(
        self, expected_raw: Any, config: NetworkEventEvaluatorCfg, context: TaskEvalContext
    ) -> Any:
        """Normalize expected value using _normalize_value helper.

        Args:
            expected_raw: Raw expected value from config
            config: Evaluator configuration
            context: Task evaluation context

        Returns:
            Normalized expected value
        """
        return self._normalize_value(
            expected_raw,
            strict=True,
            config=config,
            context=context,
        )

    def _normalized_actual_value(
        self, actual_raw: Any, normalized_expected: Any, config: NetworkEventEvaluatorCfg, context: TaskEvalContext
    ) -> Any:
        post_data = normalized_expected.get("post_data")
        post_keys = post_data.keys() if post_data else None
        if post_keys is not None:
            post_keys = tuple(k.strip() for k in post_keys)

        response_content = normalized_expected.get("response_content")
        response_content_keys = response_content.keys() if response_content else None
        if response_content_keys is not None:
            response_content_keys = tuple(k.strip() for k in response_content_keys)

        # TODO: Move this at BaseModel level
        expected_keys = []
        for key in normalized_expected:
            if normalized_expected[key] is not None:
                expected_keys.append(key)

        return self._normalize_value(
            actual_raw,
            strict=False,
            config=config,
            context=context,
            post_keys=post_keys,
            response_content_keys=response_content_keys,
            expected_keys=tuple(expected_keys),
        )

    def _normalize_response_content_field(
        self,
        normalized: dict,
        *,
        strict: bool,
        response_content_keys: tuple[str, ...] | None = None,
    ) -> None:
        """Normalize response_content field by extracting JSONPath values.

        Modifies the normalized dict in-place, replacing response_content with normalized version.

        Args:
            normalized: Dictionary containing network event data
            strict: Whether to use strict mode
            response_content_keys: Expected response_content keys (may include JSONPath expressions)
        """
        response_content_dict = normalized.get("response_content")
        if not response_content_dict:
            normalized["response_content"] = None
            return

        # Handle JSONPath extraction if response_content_keys contains JSONPath expressions
        if response_content_keys:
            # Separate regular keys from JSONPath keys
            regular_keys = [k for k in response_content_keys if not is_jsonpath_key(k)]
            jsonpath_keys = [k for k in response_content_keys if is_jsonpath_key(k)]

            flattened_actual = {}

            # Extract regular keys (existing logic)
            for key in regular_keys:
                if key in response_content_dict:
                    flattened_actual[key] = response_content_dict[key]

            # Extract JSONPath keys (new logic)
            for jsonpath_key in jsonpath_keys:
                value = extract_jsonpath_value(response_content_dict, jsonpath_key, strict=strict)
                flattened_actual[jsonpath_key] = value

            response_content_dict = flattened_actual

        normalized["response_content"] = response_content_dict

    def _normalize_response_cookies_field(
        self,
        normalized: dict,
        *,
        strict: bool,
    ) -> None:
        """Normalize response_cookies field using NormalizedString for pattern matching.

        Cookie values are already URL-decoded during extraction.
        Use NormalizedString for case-insensitive regex pattern matching.

        Args:
            normalized: Dictionary containing network event data
            strict: Whether to use strict mode
        """
        cookies_dict = normalized.get("response_cookies")
        if not cookies_dict:
            normalized["response_cookies"] = None
            return

        # Normalize each cookie value as a string (supports regex patterns)
        normalized_cookies = {}
        for cookie_name, cookie_value in cookies_dict.items():
            # NormalizedString handles regex pattern matching (^.*pattern.*$)
            normalized_cookies[cookie_name] = self.value_normalizer.normalize_single(
                cookie_value, "string", strict=strict
            )
        normalized["response_cookies"] = normalized_cookies

    def _normalize_post_data_field(
        self,
        normalized: dict,
        *,
        config: NetworkEventEvaluatorCfg,
        strict: bool,
        post_keys: tuple[str, ...] | None = None,
        context: TaskEvalContext,
    ) -> None:
        """Normalize post_data field by filtering, extracting JSONPath, and applying schema.

        Modifies the normalized dict in-place, replacing post_data with normalized version.

        Args:
            normalized: Dictionary containing network event data
            config: Evaluator configuration
            strict: Whether to use strict mode
            post_keys: Expected post_data keys (may include JSONPath expressions)
        """
        post_data_dict = normalized.get("post_data")
        if not post_data_dict:
            normalized["post_data"] = None
            return

        # Apply ignored params filtering first, immediately after confirming post_data_dict is present
        if config.ignored_post_data_params_patterns:
            post_data_dict = {k: v for k, v in post_data_dict.items() if not self._should_ignore_post_param(k, config)}

        # Handle JSONPath extraction if post_keys contains JSONPath expressions
        if post_keys:
            # Separate regular keys from JSONPath keys
            regular_keys = [k for k in post_keys if not is_jsonpath_key(k)]
            jsonpath_keys = [k for k in post_keys if is_jsonpath_key(k)]

            flattened_actual = {}

            # Extract regular keys (existing logic)
            for key in regular_keys:
                flattened_actual[key] = post_data_dict.get(key)

            # Extract JSONPath keys (new logic)
            for jsonpath_key in jsonpath_keys:
                value = extract_jsonpath_value(post_data_dict, jsonpath_key, strict=strict)
                flattened_actual[jsonpath_key] = value

            post_data_dict = flattened_actual

        # Normalize post_data values with schema (for type-aware comparison)
        if post_data_dict:
            post_data_schema = config.post_data_schema or {}

            if (
                not strict
                and self._contains_array_schema(post_data_schema)
                and not self._matches_json_schema(post_data_dict, post_data_schema)
            ):
                # Preserve the mismatched raw value so structural comparison
                # rejects it instead of coercing (for example, "2330" to 2330).
                normalized["post_data"] = post_data_dict
                return

            _derender_url_fct = partial(context.config.derender_url, sites=context.task.sites, strict=strict)
            normalized["post_data"] = self.value_normalizer.normalize(
                post_data_dict, post_data_schema, strict=strict, derender_url_fct=_derender_url_fct
            )
        else:
            normalized["post_data"] = post_data_dict

    def _normalize_headers_field(
        self,
        normalized: dict,
        *,
        context: TaskEvalContext,
        config: NetworkEventEvaluatorCfg,
        strict: bool,
    ) -> None:
        """Normalize headers field by derendering URL values.

        Modifies the normalized dict in-place, replacing headers with derendered versions.

        Args:
            normalized: Dictionary containing network event data
            context: Task evaluation context
            config: Evaluator configuration
            strict: Whether to use strict mode
        """
        headers_dict = normalized.get("headers")
        if headers_dict is None:
            return

        derendered_headers = {}
        task_sites = context.task.sites
        for header_name, header_value in headers_dict.items():
            if header_name in ["redirect_url", "referer"] and header_value:
                _normalized_url = self._normalized_url(
                    url=header_value,
                    context=context,
                    config=config,
                    strict=strict,
                    query_params=None,  # redirect_url has query params embedded in the URL string
                )
                derendered_headers[header_name] = _normalized_url
            else:
                try:
                    # Try to derender (e.g., referer URLs) and handle strings/regexp
                    _derendered = context.config.derender_url(header_value, sites=task_sites, strict=False)
                    derendered_headers[header_name] = self.value_normalizer.normalize_single(
                        _derendered, "string", strict=strict
                    )
                except Exception as e:
                    # Keep original if derendering fails
                    logger.info(f"Failed to derender header '{header_name}': {e}")
                    derendered_headers[header_name] = header_value
        normalized["headers"] = derendered_headers

    def _normalize_url_field(
        self,
        normalized: dict,
        *,
        context: TaskEvalContext,
        config: NetworkEventEvaluatorCfg,
        strict: bool,
    ) -> None:
        """Normalize URL field with query params.

        Modifies the normalized dict in-place, replacing the URL with normalized version.

        Args:
            normalized: Dictionary containing network event data
            context: Task evaluation context
            config: Evaluator configuration
            strict: Whether to use strict mode
        """
        url_value = normalized["url"]
        query_params = normalized.get("query_params")

        # Normalize URL with query_params and all URL-specific config
        # This handles: filtering, derendering, base64 decoding
        _normalized_url = self._normalized_url(
            url=url_value,
            context=context,
            config=config,
            strict=strict,
            query_params=query_params,
        )
        normalized["url"] = _normalized_url

    def _convert_to_dict_list(self, value: Any) -> tuple[list[dict], bool]:
        """Convert NetworkEventSpec value(s) to list of dictionaries.

        Args:
            value: NetworkEventSpec or list of NetworkEventSpec objects

        Returns:
            Tuple of (list of dicts, is_list_input flag)
        """
        is_list_input = False
        if isinstance(value, (list, tuple)):
            normalized_list = [
                v.model_dump(mode="json", exclude_none=True) if isinstance(v, NetworkEventSpec) else dict(v)
                for v in value
            ]
            is_list_input = True
        else:
            normalized = (
                value.model_dump(mode="json", exclude_none=True) if isinstance(value, NetworkEventSpec) else dict(value)
            )
            normalized_list = [normalized]
        return normalized_list, is_list_input

    def _normalize_value(
        self,
        value: Any,
        *,
        strict: bool,
        config: NetworkEventEvaluatorCfg,
        context: TaskEvalContext,
        post_keys: tuple[str, ...] | None = None,
        response_content_keys: tuple[str, ...] | None = None,
        expected_keys: tuple[str, ...] | None = None,
    ) -> list[MappingProxyType] | MappingProxyType | None:
        """Normalize NetworkEventSpec using data type classes.
        Returns:
            Normalized network event data as MappingProxyType or None
        """
        if not value:
            if strict:
                raise ValueError("Cannot normalize empty network event data in strict mode.")
            return None

        # Convert NetworkEventSpec to dict
        normalized_list, is_list_input = self._convert_to_dict_list(value)

        final = []
        for normalized in normalized_list:
            # Normalize each field using helper methods
            self._normalize_url_field(normalized, context=context, config=config, strict=strict)
            self._normalize_headers_field(normalized, context=context, config=config, strict=strict)
            self._normalize_post_data_field(
                normalized, config=config, strict=strict, post_keys=post_keys, context=context
            )
            self._normalize_response_content_field(
                normalized, strict=strict, response_content_keys=response_content_keys
            )
            self._normalize_response_cookies_field(normalized, strict=strict)

            # Remove query_params key as it's now embedded in normalized URL
            if "query_params" in normalized:
                del normalized["query_params"]

            final.append(MappingProxyType(normalized))

        if is_list_input:
            return final
        assert len(final) == 1
        return final[0]

    # ========================================================================
    # Event Comparison
    # ========================================================================

    def _compare_values(  # type: ignore[override]
        self,
        actual_normalized: list[MappingProxyType] | None,
        expected_normalized: MappingProxyType,
        config: NetworkEventEvaluatorCfg,
        context: TaskEvalContext,
        ordered: bool = False,
    ) -> list[EvalAssertion]:
        """Compare normalized actual vs expected using ValueComparator.

        Args:
            actual_normalized: List of normalized actual network events
            expected_normalized: Normalized expected network event
            ordered: Whether order matters (always False for network events)
            config: Evaluator configuration

        Returns:
            List of EvalAssertion objects (empty list = success)
        """
        # Check should_not_exist mode first
        if config.should_not_exist:
            if not actual_normalized:
                # Success: no events found (as expected)
                return []
            # Failure: events found when they shouldn't exist
            return [
                EvalAssertion(
                    status=EvalStatus.FAILURE,
                    assertion_name="unexpected_navigation_event",
                    assertion_msgs=(
                        f"Found {len(actual_normalized)} matching event(s) "
                        f"when none were expected (should_not_exist=True).",
                    ),
                )
            ]

        # Normal comparison mode
        if not actual_normalized:
            return [
                EvalAssertion(
                    status=EvalStatus.FAILURE,
                    assertion_name="missing_navigation_event",
                    assertion_msgs=("No matching network event found that satisfies all expected criteria.",),
                )
            ]

        # Compare each actual event against expected using full object comparison
        for actual in actual_normalized:
            # Use comparator.compare for full event comparison
            assertions = self.value_comparator.compare(
                actual=actual,
                expected=expected_normalized,
                ordered=ordered,
                value_name="network_event",
                ignore_extra_keys=True,  # Ignore extra fields in actual that aren't in expected
            )

            # If no assertions (empty list), we found a perfect match
            if not assertions:
                return []

        # No matching event found - return failure with summary
        return [
            EvalAssertion(
                status=EvalStatus.FAILURE,
                assertion_name="missing_navigation_event",
                assertion_msgs=(
                    f"No matching network event found. Checked {len(actual_normalized)} event(s) "
                    f"but none matched all expected criteria.",
                ),
            )
        ]

    # ========================================================================
    # Helper Methods - Event Filtering and Extraction
    # ========================================================================

    def _extract_event_data(
        self, event: NetworkEvent, config: NetworkEventEvaluatorCfg, context: TaskEvalContext
    ) -> NetworkEventSpec:
        """Extract raw data from network event (pure extraction, no transformations).

        All transformations (filtering, derendering, base64 decoding, normalization)
        happen during the normalization step, not here.

        Args:
            event: Network event to extract data from
            config: Evaluator configuration
            context: Task evaluation context

        Returns:
            NetworkEventSpec with raw extracted event data
        """
        # Extract raw URL (no decoding, no reconstruction, no derendering)
        url = event.url

        # Extract headers (case-insensitive matching, no derendering)
        headers = None
        if config.expected.headers:
            event_headers_lower = {
                header["name"].lower(): header["value"] for header in event.data["request"]["headers"]
            }
            extracted_headers = {}
            for expected_header_name in config.expected.headers:
                expected_header_lower = expected_header_name.lower()
                if expected_header_lower in event_headers_lower:
                    extracted_headers[expected_header_name] = event_headers_lower[expected_header_lower]
            headers = MappingProxyType(extracted_headers) if extracted_headers else None

        # Extract post_data if expected
        # Cast to SerializableMappingProxyType for type checking (Pydantic will validate/convert)
        post_data = cast("SerializableMappingProxyType | None", event.post_data if config.expected.post_data else None)

        # Extract response content if expected
        # Cast to SerializableMappingProxyType for type checking (Pydantic will validate/convert)
        response_content = cast(
            "SerializableMappingProxyType | None", event.response_content if config.expected.response_content else None
        )

        # Extract response_cookies if expected
        response_cookies = None
        if config.expected.response_cookies:
            # Get decoded cookie values
            event_cookies = event.response_cookies
            extracted_cookies = {}
            for expected_cookie_name in config.expected.response_cookies:
                if expected_cookie_name in event_cookies:
                    extracted_cookies[expected_cookie_name] = event_cookies[expected_cookie_name]
            response_cookies = MappingProxyType(extracted_cookies) if extracted_cookies else None

        # Return NetworkEventSpec object with raw data
        # Note: query_params will be extracted from URL during normalization
        return NetworkEventSpec(
            url=url,
            headers=headers,
            response_status=event.request_status,
            query_params=None,
            post_data=post_data,
            http_method=event.http_method,
            response_content=response_content,
            response_cookies=response_cookies,
        )

    @staticmethod
    def _select_navigation_events(
        events: tuple[NetworkEvent, ...], context: TaskEvalContext, config: NetworkEventEvaluatorCfg
    ) -> tuple[tuple[NetworkEvent, ...], bool]:
        if not (context.task.is_navigate_task and config.expected.http_method == "GET"):
            return events, False
        navigations = [index for index, event in enumerate(events) if event.is_navigation_event]
        if not navigations:
            return (), True
        last_navigation = navigations[-1]
        if config.navigation_only:
            return (events[last_navigation],), True
        # Earlier XHRs describe a page the agent has left or reloaded.
        return events[last_navigation + 1 :], False

    @staticmethod
    def _matches_event_query(event: NetworkEvent, config: NetworkEventEvaluatorCfg) -> bool:
        query = parse_qs(urlsplit(event.url).query, keep_blank_values=True)
        return all(query.get(key) == [value] for key, value in (config.event_query_params or {}).items())

    def _filter_events_by_criteria(
        self, events: tuple[NetworkEvent, ...], context: TaskEvalContext, config: NetworkEventEvaluatorCfg
    ) -> tuple[NetworkEvent, ...]:
        """Filter events by URL and headers criteria.

        Args:
            events: Events to filter
            context: Task evaluation context
            config: Evaluator configuration

        Returns:
            Filtered list of events matching URL and headers criteria
        """

        events, final_navigation = self._select_navigation_events(events, context, config)
        if final_navigation or not events:
            return events

        matches = []
        try:
            expected_url: URL = self._normalized_url(config.expected.url, context=context, config=config, strict=True)  # type: ignore
            expected_referer_url: URL | None = None
            if config.expected.headers and "referer" in config.expected.headers:
                expected_referer_url = self._normalized_url(
                    config.expected.headers["referer"], context=context, config=config, strict=True
                )  # type: ignore
        except Exception as e:
            logger.error(f"Error normalizing expected URL or referer for filtering: {e}")
            raise

        for event in events:
            if not self._matches_event_query(event, config):
                continue
            # Check HTTP method
            if config.expected.http_method and event.http_method.lower() != config.expected.http_method.lower():
                continue

            # Check URL path match
            try:
                event_url: URL = self._normalized_url(event.url, context=context, config=config, strict=False)  # type: ignore
                if isinstance(event_url, str):
                    raise ValueError(
                        f"Event URL '{event.url}' normalized to string ('{event_url}') instead of URL object."
                    )
            except Exception as e:
                logger.info(f"Failed to normalize event URL '{event.url}' during filtering: {e}")
                raise

            if not expected_url.compare_path(event_url):
                continue

            # Check referer header if expected
            event_referer = event.request_headers.get("referer")
            if expected_referer_url and event_referer:
                normalized_event_referer: URL = self._normalized_url(
                    event_referer, context=context, config=config, strict=False
                )  # type: ignore
                if not expected_referer_url.compare_path(normalized_event_referer):
                    continue

            matches.append(event)

        return tuple(matches)

    def _normalized_url(
        self,
        url: str | list[str],
        context: TaskEvalContext,
        config: NetworkEventEvaluatorCfg,
        strict: bool,
        query_params: dict[str, str | list[str]] | None = None,
    ) -> URL | list[URL]:
        _render_url_fct = partial(context.config.render_url, sites=context.task.sites, strict=strict)
        _derender_url_fct = partial(context.config.derender_url, sites=context.task.sites, strict=strict)
        _normalized_query_params_fct = (
            partial(self.value_normalizer.normalize, schema=config.query_params_schema, strict=strict)
            if config.query_params_schema
            else None
        )

        normalized_url: URL = self.value_normalizer.normalize_single(
            url,
            "url",
            strict=strict,
            decode_base64_query=config.decode_base64_query,
            ignored_query_parameters=config.ignored_query_params,
            ignored_query_parameters_patterns=config.ignored_query_params_patterns,
            render_url_fct=_render_url_fct,
            derender_url_fct=_derender_url_fct,
            normalize_query_params_fct=_normalized_query_params_fct,
            query_params=query_params,
        )  # type: ignore

        return normalized_url

    def _should_ignore_post_param(self, param_name: str, config: NetworkEventEvaluatorCfg) -> bool:
        """Check if a POST data parameter should be ignored based on config.

        Args:
            param_name: Name of the POST data parameter
            config: Evaluator configuration

        Returns:
            True if parameter should be ignored, False otherwise
        """
        # Check regex pattern matches
        if config.ignored_post_data_params_patterns:
            for pattern in config.ignored_post_data_params_patterns:
                try:
                    if re.search(pattern, param_name):
                        return True
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{pattern}' in ignored_post_data_params_patterns: {e}")
                    continue

        return False

    def evaluate(self, *, context: TaskEvalContext, config: NetworkEventEvaluatorCfg) -> EvaluatorResult:
        """Evaluate each runtime-bound form of a dynamic network contract."""
        candidates = self._runtime_configs(context, config)
        if not candidates:
            return super().evaluate(context=context, config=config)

        first_result: EvaluatorResult | None = None
        for candidate, source_events in candidates:
            candidate_context = context
            if source_events is not None:
                candidate_context = context.model_copy(
                    update={"network_trace": context.network_trace.model_copy(update={"events": source_events})}
                )
            result = super().evaluate(context=candidate_context, config=candidate)
            first_result = first_result or result
            if result.score == 1:
                return result
        assert first_result is not None
        return first_result

    def _runtime_configs(
        self, context: TaskEvalContext, config: NetworkEventEvaluatorCfg
    ) -> list[tuple[NetworkEventEvaluatorCfg, tuple[NetworkEvent, ...] | None]]:
        """Bind placeholders and group ordered events by resolved binding."""
        expected = config.expected.model_dump(mode="python", exclude_none=False)
        names = _placeholder_names(expected)
        candidates_by_binding: dict[
            tuple[tuple[str, str], ...], tuple[NetworkEventEvaluatorCfg, list[NetworkEvent]]
        ] = {}

        if names:
            raw_urls = expected.get("url")
            url_templates = list(raw_urls) if isinstance(raw_urls, (list, tuple)) else [raw_urls]
            post_templates = expected.get("post_data") or {}
            for event in context.network_trace.evaluation_events:
                expected_method = expected.get("http_method")
                if expected_method and event.http_method.lower() != expected_method.lower():
                    continue

                bindings: dict[str, str] = {}
                dynamic_urls = [item for item in url_templates if isinstance(item, str) and _PLACEHOLDER.search(item)]
                if dynamic_urls:
                    actual_url = context.config.derender_url(event.url, sites=context.task.sites, strict=False)
                    if not any(_template_match(item, actual_url, bindings) for item in dynamic_urls):
                        continue

                actual_post = dict(event.post_data or {})
                valid = True
                for key_template, value_template in post_templates.items():
                    actual_value = actual_post.get(key_template)
                    if isinstance(key_template, str) and _PLACEHOLDER.search(key_template):
                        matched_key = next(
                            (key for key in actual_post if _template_match(key_template, key, bindings.copy())),
                            None,
                        )
                        if matched_key is None or not _template_match(key_template, matched_key, bindings):
                            valid = False
                            break
                        actual_value = actual_post[matched_key]
                    if (
                        isinstance(value_template, str)
                        and _PLACEHOLDER.search(value_template)
                        and not _template_match(value_template, actual_value, bindings)
                    ):
                        valid = False
                        break
                if valid and set(bindings) == names:
                    corrected_expected = _substitute_placeholders(expected, bindings)
                    binding_key = tuple(sorted(bindings.items()))
                    if binding_key not in candidates_by_binding:
                        candidates_by_binding[binding_key] = (
                            config.model_copy(
                                update={"expected": config.expected.model_copy(update=corrected_expected)}
                            ),
                            [],
                        )
                    candidates_by_binding[binding_key][1].append(event)

            candidates = [
                (candidate, tuple(source_events)) for candidate, source_events in candidates_by_binding.values()
            ]
        else:
            candidates = [(config, None)]

        return [(self._with_inferred_post_schema(candidate), source_event) for candidate, source_event in candidates]

    @staticmethod
    def _with_inferred_post_schema(config: NetworkEventEvaluatorCfg) -> NetworkEventEvaluatorCfg:
        """Preserve singleton array semantics when the contract omits a schema."""
        post_data = config.expected.post_data or {}
        singleton_arrays = {
            key for key, value in post_data.items() if isinstance(value, (list, tuple)) and len(value) == 1
        }
        if not singleton_arrays or config.post_data_schema:
            return config
        schema = {
            "type": "object",
            "properties": {
                key: {
                    "type": "array",
                    "items": NetworkEventEvaluator._schema_for_json_value(post_data[key][0]),
                }
                for key in singleton_arrays
            },
        }
        return config.model_copy(update={"post_data_schema": schema})

    @staticmethod
    def _schema_for_json_value(value: Any) -> dict[str, Any]:
        """Infer a JSON schema without coercing distinct scalar types."""
        if value is None:
            schema = {"type": "null"}
        elif isinstance(value, bool):
            schema = {"type": "boolean"}
        elif isinstance(value, int):
            schema = {"type": "integer"}
        elif isinstance(value, float):
            schema = {"type": "number"}
        elif isinstance(value, str):
            schema = {"type": "string"}
        elif isinstance(value, Mapping):
            schema = {
                "type": "object",
                "properties": {key: NetworkEventEvaluator._schema_for_json_value(item) for key, item in value.items()},
            }
        elif isinstance(value, (list, tuple)):
            schema = {
                "type": "array",
                "items": NetworkEventEvaluator._schema_for_json_value(value[0]) if value else {},
            }
        else:
            raise TypeError(f"Cannot infer a POST data schema for {type(value).__name__}")
        return schema

    @staticmethod
    def _matches_json_schema(value: Any, schema: Mapping[str, Any]) -> bool:
        """Check the JSON types used by inferred singleton-array schemas."""
        schema_type = schema.get("type")
        if schema_type == "null":
            matches = value is None
        elif schema_type == "boolean":
            matches = isinstance(value, bool)
        elif schema_type == "integer":
            matches = isinstance(value, int) and not isinstance(value, bool)
        elif schema_type == "number":
            matches = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif schema_type == "string":
            matches = isinstance(value, str)
        elif schema_type == "array":
            item_schema = schema.get("items", {})
            matches = isinstance(value, (list, tuple)) and all(
                NetworkEventEvaluator._matches_json_schema(item, item_schema) for item in value
            )
        elif schema_type == "object":
            if isinstance(value, Mapping):
                matches = all(
                    key in value and NetworkEventEvaluator._matches_json_schema(value[key], property_schema)
                    for key, property_schema in schema.get("properties", {}).items()
                )
            else:
                matches = False
        else:
            matches = True
        return matches

    @staticmethod
    def _contains_array_schema(schema: Mapping[str, Any]) -> bool:
        """Return whether a schema contains an array at any depth."""
        if schema.get("type") == "array":
            return True
        properties = schema.get("properties", {})
        return isinstance(properties, Mapping) and any(
            isinstance(property_schema, Mapping) and NetworkEventEvaluator._contains_array_schema(property_schema)
            for property_schema in properties.values()
        )
