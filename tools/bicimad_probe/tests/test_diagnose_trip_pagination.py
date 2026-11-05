from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diagnose_trip_pagination import (
    format_safe_report,
    paginate_trip_history,
)
from mpass_client import JsonResponse, ProbeRequestError


class PaginationDiagnosticTests(unittest.TestCase):
    def test_uses_official_page_sequence_and_stops_on_empty_page(self) -> None:
        fetcher = FakePageFetcher(
            [
                _response([_trip("trip-a"), _trip("trip-b")]),
                _response([_trip("trip-c"), _trip("trip-d")]),
                _response([]),
            ]
        )

        result = paginate_trip_history(fetcher, pause_seconds=0)

        self.assertEqual(fetcher.pages, [None, 1, 2])
        self.assertEqual(result.page_size, 2)
        self.assertEqual(result.pages_with_data, 2)
        self.assertEqual(result.unique_trip_count, 4)
        self.assertEqual(result.stop_reason, "empty_page")

    def test_stops_on_short_page(self) -> None:
        fetcher = FakePageFetcher(
            [
                _response([_trip("trip-a"), _trip("trip-b")]),
                _response([_trip("trip-c")]),
            ]
        )

        result = paginate_trip_history(fetcher, pause_seconds=0)

        self.assertEqual(result.unique_trip_count, 3)
        self.assertEqual(result.stop_reason, "short_page")

    def test_deduplicates_partial_overlap_between_pages(self) -> None:
        fetcher = FakePageFetcher(
            [
                _response([_trip("trip-a"), _trip("trip-b")]),
                _response([_trip("trip-b"), _trip("trip-c")]),
                _response([]),
            ]
        )

        result = paginate_trip_history(fetcher, pause_seconds=0)

        self.assertEqual(result.unique_trip_count, 3)
        self.assertEqual(result.duplicate_trip_count, 1)
        self.assertEqual(result.overlap_page_count, 1)

    def test_stops_when_a_full_page_repeats(self) -> None:
        page = [_trip("trip-a"), _trip("trip-b")]
        fetcher = FakePageFetcher([_response(page), _response(page)])

        result = paginate_trip_history(fetcher, pause_seconds=0)

        self.assertEqual(result.stop_reason, "fully_repeated_page")
        self.assertEqual(result.unique_trip_count, 2)
        self.assertEqual(result.duplicate_trip_count, 2)
        self.assertEqual(fetcher.pages, [None, 1])

    def test_stops_on_explicit_end_marker(self) -> None:
        fetcher = FakePageFetcher(
            [
                JsonResponse(
                    status=200,
                    payload={
                        "code": "00",
                        "data": [_trip("trip-a"), _trip("trip-b")],
                        "pagination": {"hasMore": False},
                    },
                )
            ]
        )

        result = paginate_trip_history(fetcher, pause_seconds=0)

        self.assertEqual(result.stop_reason, "explicit_end")
        self.assertEqual(result.unique_trip_count, 2)

    def test_stops_at_safety_limit(self) -> None:
        fetcher = GeneratingPageFetcher()

        result = paginate_trip_history(
            fetcher,
            max_pages=3,
            pause_seconds=0,
        )

        self.assertEqual(result.stop_reason, "safety_limit")
        self.assertEqual(result.requests_made, 3)
        self.assertEqual(result.unique_trip_count, 6)

    def test_backend_error_is_reported_without_private_payloads(self) -> None:
        fetcher = FakePageFetcher(
            [
                _response([_trip("private-trip-a"), _trip("private-trip-b")]),
                ProbeRequestError(
                    stage="trips",
                    status=429,
                    api_code="88",
                    api_description="private backend description",
                    error_type="HTTPError",
                ),
            ]
        )

        result = paginate_trip_history(fetcher, pause_seconds=0)
        report = format_safe_report(result)

        self.assertEqual(result.stop_reason, "backend_error")
        self.assertIn("HTTP al detenerse: 429", report)
        self.assertIn("Codigo API al detenerse: 88", report)
        self.assertNotIn("private-trip", report)
        self.assertNotIn("private backend description", report)

    def test_retries_same_page_once_after_ssl_zero_return(self) -> None:
        transient_error = ProbeRequestError(
            stage="trips",
            status=None,
            api_code=None,
            api_description=None,
            error_type="SSLZeroReturnError",
        )
        fetcher = FakePageFetcher(
            [
                _response([_trip("trip-a"), _trip("trip-b")]),
                transient_error,
                _response([_trip("trip-c"), _trip("trip-d")]),
                _response([]),
            ]
        )
        sleeps: list[float] = []

        result = paginate_trip_history(
            fetcher,
            pause_seconds=0,
            retry_delay_seconds=2,
            sleeper=sleeps.append,
        )

        self.assertEqual(fetcher.pages, [None, 1, 1, 2])
        self.assertEqual(result.requests_made, 4)
        self.assertEqual(result.transient_retry_count, 1)
        self.assertEqual(result.unique_trip_count, 4)
        self.assertEqual(result.stop_reason, "empty_page")
        self.assertEqual(sleeps, [2])

    def test_stops_if_ssl_zero_return_repeats_after_retry(self) -> None:
        def ssl_error() -> ProbeRequestError:
            return ProbeRequestError(
                stage="trips",
                status=None,
                api_code=None,
                api_description=None,
                error_type="SSLZeroReturnError",
            )

        fetcher = FakePageFetcher(
            [
                _response([_trip("trip-a"), _trip("trip-b")]),
                ssl_error(),
                ssl_error(),
            ]
        )

        result = paginate_trip_history(
            fetcher,
            pause_seconds=0,
            retry_delay_seconds=0,
        )

        self.assertEqual(fetcher.pages, [None, 1, 1])
        self.assertEqual(result.requests_made, 3)
        self.assertEqual(result.transient_retry_count, 1)
        self.assertEqual(result.stop_reason, "backend_error")
        self.assertEqual(result.error_type, "SSLZeroReturnError")

    def test_report_contains_only_approximate_months_not_trip_details(self) -> None:
        fetcher = FakePageFetcher(
            [
                _response(
                    [
                        _trip(
                            "private-trip-a",
                            started_at="2025-01-02T03:04:05+01:00",
                        ),
                        _trip(
                            "private-trip-b",
                            started_at="2026-07-08T09:10:11+02:00",
                        ),
                    ]
                ),
                _response([]),
            ]
        )

        report = format_safe_report(paginate_trip_history(fetcher, pause_seconds=0))

        self.assertIn("2025-01", report)
        self.assertIn("2026-07", report)
        self.assertNotIn("private-trip", report)
        self.assertNotIn("Private Station", report)
        self.assertNotIn("2025-01-02T03:04:05", report)

    def test_counts_missing_trip_ids_without_exposing_rows(self) -> None:
        fetcher = FakePageFetcher(
            [
                _response(
                    [
                        _trip("trip-a"),
                        {"undock": {"undock_ts": "2026-01-01T10:00:00"}},
                    ]
                ),
                _response([]),
            ]
        )

        result = paginate_trip_history(fetcher, pause_seconds=0)

        self.assertEqual(result.unique_trip_count, 1)
        self.assertEqual(result.missing_trip_id_count, 1)


class FakePageFetcher:
    def __init__(self, responses: list[JsonResponse | Exception]) -> None:
        self.responses = list(responses)
        self.pages: list[int | None] = []

    def __call__(self, page: int | None) -> JsonResponse:
        self.pages.append(page)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class GeneratingPageFetcher:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self, page: int | None) -> JsonResponse:
        current = self.index
        self.index += 1
        return _response([_trip(f"trip-{current}-a"), _trip(f"trip-{current}-b")])


def _response(data: list[dict]) -> JsonResponse:
    return JsonResponse(status=200, payload={"code": "00", "data": data})


def _trip(
    trip_id: str,
    *,
    started_at: str = "2026-06-15T12:30:00+02:00",
) -> dict:
    return {
        "trip_id": trip_id,
        "undock": {
            "undock_ts": started_at,
            "undock_station_name": "Private Station",
        },
    }


if __name__ == "__main__":
    unittest.main()
