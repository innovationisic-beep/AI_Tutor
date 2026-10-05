class OrchestratorService:
    async def decide_next_action(
        self,
        mastery_score: float,
        last_answer_correct: bool | None = None,
        has_recent_mistakes: bool = False,
    ) -> dict:
        if mastery_score < 40:
            result = {
                "action": "EXPLAIN",
                "difficulty": "easy",
            }
        elif mastery_score < 70:
            if last_answer_correct is False:
                result = {
                    "action": "REVISE",
                    "difficulty": "easy",
                }
            else:
                result = {
                    "action": "QUIZ",
                    "difficulty": "medium",
                }
        else:
            result = {
                "action": "QUIZ",
                "difficulty": "hard",
            }

        action = result["action"]
        print(f"[Orchestrator] mastery={mastery_score}, action={action}")
        return result
