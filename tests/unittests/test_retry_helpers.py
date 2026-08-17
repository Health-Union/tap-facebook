"""
Test coverage for retry_helpers.py
"""

import unittest
from unittest.mock import Mock, patch

from tap_facebook import AdsInsights, FacebookRequestError


@patch("time.sleep")
class TestRetryingGetResult(unittest.TestCase):
    """`AdsInsights.__attrs_post_init__` builds `self._retrying_get_result`  
    to survive Facebook's async-job eventual-consistency race: the job can report 
    "Job Completed" while polling, but the report data isn't queryable yet, 
    producing a 400 "The adreport job is not completed yet" error on 
    the immediately-following `get_result()` call.
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
        mocked_job = Mock()
        mocked_job.get_result.__name__ = "get_result"
        mocked_job.get_result.side_effect = self._make_400_error(
            "(#100) The adreport job is not completed yet")

        ad_insights_object = AdsInsights('', Mock(), '', '', {}, {})
        with self.assertRaises(FacebookRequestError):
            ad_insights_object._retrying_get_result(mocked_job.get_result)()
        # 5 is the max tries specified in the tap
        self.assertEqual(5, mocked_job.get_result.call_count)

    def test_does_not_retry_unrelated_400_error(self, mocked_sleep):
        """A 400 error that doesn't match the known transient pattern should
        NOT be retried, and should propagate on the first attempt.
        """
        mocked_job = Mock()
        mocked_job.get_result.__name__ = "get_result"
        mocked_job.get_result.side_effect = self._make_400_error("Invalid parameter")

        ad_insights_object = AdsInsights('', Mock(), '', '', {}, {})
        with self.assertRaises(FacebookRequestError):
            ad_insights_object._retrying_get_result(mocked_job.get_result)()
        self.assertEqual(1, mocked_job.get_result.call_count)

    def test_retries_and_succeeds_once_job_is_ready(self, mocked_sleep):
        """If the 'not completed yet' error clears up on a later attempt,
        the retrying call should return the successful result.
        """
        error = self._make_400_error("(#100) The adreport job is not completed yet")
        rows = [{"date_stop": "2026-07-01"}]
        mocked_job = Mock()
        mocked_job.get_result.__name__ = "get_result"
        mocked_job.get_result.side_effect = [error, error, rows]

        ad_insights_object = AdsInsights('', Mock(), '', '', {}, {})
        result = ad_insights_object._retrying_get_result(mocked_job.get_result)()
        self.assertEqual(rows, result)
        self.assertEqual(3, mocked_job.get_result.call_count)
