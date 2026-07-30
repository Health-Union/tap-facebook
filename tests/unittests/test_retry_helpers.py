"""
Test coverage for retry_helpers.py
"""

import unittest
from unittest.mock import Mock, patch

from tap_facebook import FacebookRequestError, call_with_retry


@patch("time.sleep")
class TestCallWithRetry(unittest.TestCase):
    """`call_with_retry` is monkey-patched onto `FacebookAdsApi.call` and wraps two
    stacked decorators -- `retry_on_summary_param_error` (upstream) and
    `retry_on_adreport_job_not_ready_error` (tap_facebook/retry_helpers.py, added in
    this fork) -- each retrying its own known-transient 400 error (regex-matched on
    the error message). These tests exercise both through that shared entry point.
    """

    @staticmethod
    def _make_400_error(message):
        return FacebookRequestError(
            message=message,
            request_context={"": Mock()},
            http_status=400,
            http_headers=Mock(),
            body={"error": {"message": message}}
        )

    def test_retries_on_adreport_job_not_completed_error(self, mocked_sleep):
        """The async insights job can report 'Job Completed' while polling, but the
        report data isn't queryable yet. Facebook returns a 400 'adreport job is not
        completed yet' error in that window, which should be retried.
        """
        error = self._make_400_error("(#100) The adreport job is not completed yet")
        with patch("tap_facebook.original_call", side_effect=error) as mocked_original_call:
            with self.assertRaises(FacebookRequestError):
                call_with_retry(Mock(), "GET", "/some/path")
            # 5 is the max tries specified in the tap
            self.assertEqual(5, mocked_original_call.call_count)

    def test_retries_on_summary_param_error(self, mocked_sleep):
        """A 400 error about fields missing from the summary param is a known
        transient error (upstream logic) and should still be retried.
        """
        message = ("(#100) Cannot include clicks, impressions in summary param "
                   "because they weren't there while creating the report run")
        error = self._make_400_error(message)
        with patch("tap_facebook.original_call", side_effect=error) as mocked_original_call:
            with self.assertRaises(FacebookRequestError):
                call_with_retry(Mock(), "GET", "/some/path")
            # 5 is the max tries specified in the tap
            self.assertEqual(5, mocked_original_call.call_count)

    def test_does_not_retry_unrelated_400_error(self, mocked_sleep):
        """A 400 error that doesn't match either known transient pattern should
        NOT be retried, and should propagate on the first attempt.
        """
        error = self._make_400_error("Invalid parameter")
        with patch("tap_facebook.original_call", side_effect=error) as mocked_original_call:
            with self.assertRaises(FacebookRequestError):
                call_with_retry(Mock(), "GET", "/some/path")
            self.assertEqual(1, mocked_original_call.call_count)

    def test_retries_and_succeeds_once_job_is_ready(self, mocked_sleep):
        """If the 'not completed yet' error clears up on a later attempt,
        `call_with_retry` should return the successful result.
        """
        error = self._make_400_error("(#100) The adreport job is not completed yet")
        success = {"data": []}
        with patch("tap_facebook.original_call", side_effect=[error, error, success]) as mocked_original_call:
            result = call_with_retry(Mock(), "GET", "/some/path")
            self.assertEqual(success, result)
            self.assertEqual(3, mocked_original_call.call_count)
