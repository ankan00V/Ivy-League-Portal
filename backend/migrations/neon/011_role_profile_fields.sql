-- Fields the non-student roles actually need.
--
-- Onboarding asked every role the student questions - university, course,
-- skills, interests, preferred work mode - because those were the only fields
-- that existed. An institution has no skills and no preferred work mode; it has
-- an AISHE code, a type, and a contact person. Asking it the student questions
-- is asking questions from somebody else's form, and storing the answers
-- nowhere is worse.
--
-- All nullable: a student profile leaves every one of these empty, and an
-- institution profile leaves the student ones empty.

ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS department text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS designation text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS specialisation text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS teaching_experience_years integer;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS vidwan_id text;

ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS institution_type text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS aishe_code text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS institution_city text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS institution_state text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS institution_website text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS contact_designation text;
ALTER TABLE app.profiles ADD COLUMN IF NOT EXISTS student_strength integer;

-- The institution portal matches its cohort partly on college name; an AISHE
-- code is the identifier that could replace that guesswork later.
CREATE INDEX IF NOT EXISTS profiles_aishe_code_idx ON app.profiles (aishe_code);
