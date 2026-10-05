# Backend scripts

## Seed test curriculum

Inserts a minimal curriculum for testing the recommendation engine:

- **1 subject:** Mathematics (grade 6)
- **4 topics:** Fractions, Decimals, Percentages, Algebra Basics
- **3 progression edges:** Fractions → Decimals (60), Fractions → Percentages (70), Fractions → Algebra Basics (80)

Uses the same `organization_id` as existing records (first organization, or from existing subject/user).
.......
**Run from the `backend` directory:**

```bash
cd backend
python -m scripts.seed_curriculum
```

Ensure `.env` has `MONGODB_URL` set and at least one organization exists (e.g. from a user registration).

## Backfill quiz_stage / question_type

Structured concept-check and cluster-quiz ignore bank rows with `quiz_stage=null`.

```bash
cd backend
# Inventory only
python -m app.scripts.backfill_quiz_stage

# Write inferred question_type, then assign stage heuristics
python -m app.scripts.backfill_quiz_stage --apply-type --apply-stage
```

