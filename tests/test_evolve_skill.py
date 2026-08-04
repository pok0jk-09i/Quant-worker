import unittest
from unittest import mock
import io

from scripts.evolve_skill import emit_stage_progress, fetch_user_alphas


class EvolveSkillPaginationTests(unittest.TestCase):
    def test_emit_stage_progress_prints_machine_readable_stage_line(self):
        stream = io.StringIO()

        with mock.patch("sys.stdout", stream):
            emit_stage_progress("fetch_pnl", "10/200")

        self.assertEqual(stream.getvalue().strip(), "stage: fetch_pnl | 10/200")

    def test_fetch_user_alphas_stops_cleanly_when_offset_contract_breaks_after_first_page(self):
        session = mock.Mock()
        first = mock.Mock()
        first.status_code = 200
        first.json.return_value = {
            "results": [
                {"id": "a1", "status": "ACTIVE"},
                {"id": "a2", "status": "UNSUBMITTED"},
            ]
        }
        second = mock.Mock()
        second.status_code = 400
        second.text = '["Invalid offset. Please use filters to narrow down the result."]'

        with mock.patch(
            "scripts.evolve_skill.get_with_retry",
            side_effect=[first, second],
        ), mock.patch("scripts.evolve_skill.time.sleep"):
            alphas = fetch_user_alphas(session, limit=2)

        self.assertEqual([alpha["id"] for alpha in alphas], ["a1", "a2"])

    def test_fetch_user_alphas_stops_when_pagination_repeats_without_forward_progress(self):
        session = mock.Mock()
        first = mock.Mock()
        first.status_code = 200
        first.json.return_value = {
            "results": [
                {"id": "a1", "status": "ACTIVE"},
                {"id": "a2", "status": "UNSUBMITTED"},
            ]
        }
        repeated = mock.Mock()
        repeated.status_code = 200
        repeated.json.return_value = {
            "results": [
                {"id": "a1", "status": "ACTIVE"},
                {"id": "a2", "status": "UNSUBMITTED"},
            ]
        }

        with mock.patch(
            "scripts.evolve_skill.get_with_retry",
            side_effect=[first, repeated],
        ), mock.patch("scripts.evolve_skill.time.sleep"):
            alphas = fetch_user_alphas(session, limit=2)

        self.assertEqual([alpha["id"] for alpha in alphas], ["a1", "a2"])


if __name__ == "__main__":
    unittest.main()
