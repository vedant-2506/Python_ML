"""Collect a manual candidate answer from the terminal and save it as pending."""

from __future__ import annotations

from .database import get_stage1_questions, save_candidate_answer


def collect_multiline_answer() -> str:
    """Read a multiline candidate answer until done is entered."""

    print("Enter Candidate Answer:")
    print("(Type done on a separate line when this answer is complete)")
    lines = []
    while True:
        raw = input()
        if raw.strip().lower() == "done":
            break
        lines.append(raw)
    return "\n".join(lines)


def main() -> None:
    print("========================================")
    print("     MANUAL CANDIDATE ANSWER INPUT")
    print("========================================")

    try:
        jd_id = int(input("Enter JD ID: ").strip())
        candidate_id = int(input("Enter Candidate ID: ").strip())
    except ValueError:
        print("Invalid JD ID or Candidate ID. Please enter numeric values.")
        return

    try:
        if jd_id < 1 or candidate_id < 1:
            raise ValueError("JD ID and Candidate ID must be positive integers.")
        questions = get_stage1_questions(jd_id)
    except ValueError as exc:
        print(f"Could not load questions: {exc}")
        return
    except Exception as exc:
        print(f"Database error while loading questions: {exc}")
        return

    for order, question in enumerate(questions, start=1):
        print(f"\nQuestion {order}: {question['question']}")
        candidate_answer = collect_multiline_answer()
        try:
            save_candidate_answer(
                jd_id,
                int(question["question_id"]),
                candidate_answer,
                candidate_id,
            )
        except ValueError as exc:
            print(f"Could not save answer for question {order}: {exc}")
            return
        except Exception as exc:
            print(f"Database error while saving answer for question {order}: {exc}")
            return
        print(f"Answer {order} saved.")

    while input("\nType finish to complete submission: ").strip().lower() != "finish":
        print("Please type finish to complete submission.")
    print("All six answers were saved successfully.")


if __name__ == "__main__":
    main()
