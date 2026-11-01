def save_and_evaluate(exam_id: str, jd_id: int, candidate_id: int, question_id: int,
                      answer: str, source: str, stage: int) -> None:
    from Answer_Checking.database import save_candidate_answer
    from Answer_Checking.answer_evaluator import evaluate_record_by_id
    evaluation_id = save_candidate_answer(jd_id=jd_id, question_id=question_id,
                                          candidate_answer=answer, candidate_id=candidate_id,
                                          exam_id=exam_id, question_source=source)
    evaluate_record_by_id(evaluation_id)


def calculate_final(exam_id: str, candidate_id: int, jd_id: int) -> None:
    from Answer_Checking.final_result import calculate_and_store_final_result
    calculate_and_store_final_result(exam_id, candidate_id, jd_id)
