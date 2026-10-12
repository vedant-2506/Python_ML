"""Command-line entry point to evaluate pending answers."""

from __future__ import annotations

import argparse
import traceback

from .answer_evaluator import evaluate_pending_record
from .database import (
    get_evaluation_by_id,
    get_first_six_average,
    get_pending_answers,
    update_evaluation_result,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate pending answer rows in the RankResume PostgreSQL database.")
    parser.add_argument("--evaluation-id", type=int, help="Evaluate one specific evaluation record.")
    parser.add_argument("--limit", type=int, help="Limit the number of pending records processed in this run.")
    args = parser.parse_args()

    if args.evaluation_id is not None:
        record = get_evaluation_by_id(args.evaluation_id)
        if record is None:
            raise ValueError(f"No evaluation record found for evaluation_id={args.evaluation_id}")
        if record.get("evaluation_status") != "Pending":
            raise ValueError(
                f"Evaluation {args.evaluation_id} is not pending; refusing to replace its existing result."
            )
        records = [record]
    else:
        records = get_pending_answers()
        if args.limit is not None:
            records = records[: args.limit]

    total = len(records)
    successfully_evaluated = 0
    review_required = 0
    failed = 0

    print("========================================")
    print("       ANSWER EVALUATION SUMMARY")
    print("========================================")
    print(f"Total Pending Answers: {total}")

    for record in records:
        try:
            result = evaluate_pending_record(record)
            update_evaluation_result(record["evaluation_id"], result)
            if result.get("evaluation_status") == "Review Required":
                review_required += 1
            else:
                successfully_evaluated += 1
        except Exception as exc:
            failed += 1
            print(f"Failed evaluation for evaluation_id={record.get('evaluation_id')}: {exc}")
            print(traceback.format_exc())

    print(f"Successfully Evaluated: {successfully_evaluated}")
    print(f"Review Required: {review_required}")
    print(f"Failed Evaluations: {failed}")

    attempts = {
        (str(record["attempt_id"]), record["jd_id"])
        for record in records
        if record.get("attempt_id") is not None
    }
    for attempt_id, jd_id in sorted(attempts):
        try:
            average = get_first_six_average(attempt_id, jd_id)
            if average is None:
                print(
                    f"First Six Average for JD {jd_id}, attempt {attempt_id}: "
                    "not ready (requires six distinct scored Stage 1 answers)."
                )
            else:
                print(
                    f"First Six Average for JD {jd_id}, attempt {attempt_id}: "
                    f"{average} / 100 (provisional if any answer requires review)."
                )
        except Exception as exc:
            print(
                f"Could not calculate First Six Average for JD {jd_id}, "
                f"attempt {attempt_id}: {exc}"
            )


if __name__ == "__main__":
    main()
