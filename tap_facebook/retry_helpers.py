#!/usr/bin/env python3
"""
Health-Union-specific retry helpers.
"""
import re
import sys

import backoff
import singer
from facebook_business.exceptions import FacebookRequestError

LOGGER = singer.get_logger()

ADREPORT_JOB_NOT_READY_PATTERN = r'.*[Tt]he adreport job is not completed yet'


def retry_on_adreport_job_not_ready_error(backoff_type, exception, **wait_gen_kwargs):
    """
    The async insights job can report `async_status == "Job Completed"` while we're
    polling it, but the underlying report data isn't queryable yet (Facebook-side
    eventual consistency). Facebook returns a 400 error with the message "The
    adreport job is not completed yet" in that window. Retrying shortly after
    succeeds.
    """
    def log_retry_attempt(details):
        _, exc, _ = sys.exc_info()
        LOGGER.info('Caught "adreport job not ready" error after %s tries. '
                    'Waiting %s more seconds then retrying...',
                    details["tries"], details["wait"])

    def should_retry_api_error(exc):
        if isinstance(exc, FacebookRequestError):
            message = (exc._error or {}).get('message', '')  # pylint: disable=protected-access
            return exc.http_status() == 400 and bool(re.match(ADREPORT_JOB_NOT_READY_PATTERN, message))
        return False

    return backoff.on_exception(
        backoff_type,
        exception,
        jitter=None,
        on_backoff=log_retry_attempt,
        giveup=lambda exc: not should_retry_api_error(exc),
        **wait_gen_kwargs
    )
