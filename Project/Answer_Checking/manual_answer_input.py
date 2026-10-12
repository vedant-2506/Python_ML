"""Collect a manual candidate answer from the terminal and save it as pending."""

from __future__ import annotations

from .database import save_candidate_answer


def collect_multiline_answer() -> str:
    """Read a multiline candidate answer until END_ANSWER is entered."""

    print("Enter Candidate Answer:")
    print("(Type END_ANSWER on a separate line to finish)")
    lines = []
    while True:
        raw = input()
        if raw.strip() == "END_ANSWER":
            break
        lines.append(raw)
    return "\n".join(lines)


def main() -> None:
    print("========================================")
    print("     MANUAL CANDIDATE ANSWER INPUT")
    print("========================================")

    try:
        jd_id = int(input("Enter JD ID: ").strip())
        question_id = int(input("Enter Question ID: ").strip())
    except ValueError:
        print("Invalid JD ID or Question ID. Please enter numeric values.")
        return

    attempt_id = input(
        "Enter candidate-scoped attempt ID (reuse this UUID for all six answers in the attempt): "
    ).strip()
    candidate_answer = collect_multiline_answer()
    try:
        evaluation_id = save_candidate_answer(
            jd_id,
            question_id,
            candidate_answer,
            attempt_id,
        )
    except ValueError as exc:
        print(f"Could not save answer: {exc}")
        return
    except Exception as exc:
        print(f"Database error while saving candidate answer: {exc}")
        return

    print("\nCandidate answer saved successfully!")
    print(f"Evaluation ID: {evaluation_id}")
    print("Evaluation Status: Pending")


if __name__ == "__main__":
    main()
