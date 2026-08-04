import io
import unittest
from contextlib import redirect_stdout

from scripts.submit_batch import print_summary


class SubmitBatchSummaryTests(unittest.TestCase):
    def test_print_summary_tolerates_already_submitted_active_without_submission_alpha_payload(self):
        results = [
            {
                "metrics": {
                    "id": "wpRZaR3d",
                    "is": {
                        "sharpe": 2.39,
                        "fitness": 1.92,
                        "turnover": 0.165,
                    },
                },
                "submission": {
                    "submitted": False,
                    "reason": "already_submitted",
                    "status": "ACTIVE",
                    "stage": "OS",
                },
            }
        ]

        stream = io.StringIO()
        with redirect_stdout(stream):
            print_summary(results)

        output = stream.getvalue()
        self.assertIn("ACTIVE: 1", output)
        self.assertIn("ACTIVE wpRZaR3d", output)


if __name__ == "__main__":
    unittest.main()
