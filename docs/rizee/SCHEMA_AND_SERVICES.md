# Rizee Foundation — Proposed Data Model & Service Breakdown

Status: **proposal, awaiting review**. No implementation code written yet.
Sources: implementation prompt (Sections 1–12) + `IIT Foundation Requirements.pdf` (PRD v1.0).

---

## Part A — Service / module breakdown

### Monorepo layout

```
/apps
  /api                          Node 20 + Express + Prisma
    /src
      /modules                  one folder per bounded service
        /auth                   routes, controller, service, tokens, guards
        /content                curriculum, notes, saved library
        /assessment             question bank, practice, tests, grading
        /analytics              event ingestion, metrics, dashboards
        /recommendation         weak-topic detection, AI suggestions
        /planner                goals, daily plans, rescheduling
        /revision               queue, priority engine, revision packs
        /notification           reminders, alerts
        /admin                  syllabus/content/user management, audit
      /ai                       AIService (single Anthropic wrapper) + prompts
      /events                   EventBus interface + in-process impl (+ BullMQ impl later)
      /db                       Prisma client singleton, transaction helpers
      /http                     app.ts, middleware, error handler, validation (zod)
      /jobs                     scheduled/queued workers (nightly rollups, replanning)
    /prisma                     schema.prisma, migrations, seed
    /test
  /web                          React 18 + Vite + React Router + TanStack Query + Tailwind
    /src
      /app                      router, providers, role guards
      /features                 dashboard, learn, practice, assessment,
                                analytics, revision, planner, library,
                                parent, teacher, admin
      /components               design-system primitives
      /api                      typed fetch clients (one per backend module)
      /store                    Zustand slices (UI state only)
/packages
  /shared                       enums, DTO types, zod schemas, event names,
                                scoring constants — imported by BOTH apps
```

Every module exposes exactly one internal facade (`modules/x/x.service.ts`).
Cross-module calls go through that facade, never through another module's
repository or Prisma models directly — that's what keeps them independently
deployable later.

### Service responsibilities

| Service | Owns (tables) | Publishes events | Consumes |
|---|---|---|---|
| **Auth** | User, RefreshToken, ParentStudentLink, ClassroomMember | `user.registered`, `user.logged_in` | — |
| **Content** | ClassLevel, Subject, Chapter, Topic, TopicPrerequisite, Note, SavedItem, TopicProgress | `topic.read`, `topic.completed`, `snippet.saved`, `reading.session_ended` | — |
| **Assessment** | Question, QuestionOption, PracticeSession, Assessment, AssessmentQuestion, AssessmentResult, QuestionAttempt, AttemptErrorTag | `practice.completed`, `assessment.submitted`, `question.answered`, `error.detected` | Content (topic metadata) |
| **Analytics** | AnalyticsEvent, MetricSnapshot, TopicMastery, StudyDay | `mastery.updated`, `weakness.detected` | all events |
| **Revision** | RevisionQueueItem, RevisionPack, RevisionPackItem | `revision.queued`, `revision.completed` | `assessment.submitted`, `error.detected`, `mastery.updated` |
| **Recommendation** | Recommendation | `recommendation.created` | Analytics + Revision + Content |
| **Planner** | Goal, DailyStudyPlan, DailyTask, ReadinessSnapshot | `plan.generated`, `task.missed`, `task.completed` | Analytics + Revision + Content |
| **Notification** | Notification | — | `task.missed`, `revision.queued`, streak events |
| **Admin** | AuditLog (+ write access to Content/Question with review workflow) | `content.published` | — |

### Event pipeline (the "event-driven analytics" requirement)

```
module → eventBus.publish(DomainEvent)
             │
             ├─ AnalyticsEvent row written synchronously (append-only audit of every interaction)
             └─ handlers dispatched asynchronously
                  ├─ Analytics: update TopicMastery / StudyDay / MetricSnapshot
                  ├─ Revision:  enqueue weak topics per the priority table
                  ├─ Recommendation: invalidate + regenerate suggestions
                  └─ Planner:  mark tasks complete, trigger replanning
```

`EventBus` is an interface with two implementations: `InProcessEventBus`
(Phase 1, Node EventEmitter + `setImmediate`) and `RedisEventBus` (BullMQ,
Phase 2+). Publishers never know which is active. Handlers are idempotent and
keyed by `eventId` so a queue-backed retry can't double-count mastery.

### Cross-cutting

- **AIService** — the only place the Anthropic SDK is imported. Interface:
  `generateNote`, `summariseForRevisionPack`, `categoriseError`,
  `recommendNextActivity`, `explainAnswer`. Each takes a typed input, returns a
  typed output, handles retry/timeout/JSON-repair, and logs token usage to
  `AiUsageLog`. Every method has a deterministic fallback so the platform
  degrades rather than fails when the API is unavailable.
- **RBAC** — `requireRole(...roles)` middleware plus a resource-scoping helper
  (`assertCanReadStudent(actor, studentId)`) that resolves parent links and
  teacher-classroom links. Applied from day one, on every route.
- **Audit** — all admin mutations wrapped in `withAudit()`.

---

## Part B — Prisma schema (proposed)

```prisma
generator client { provider = "prisma-client-js" }
datasource db    { provider = "postgresql"; url = env("DATABASE_URL") }

// ──────────────────────────── enums ────────────────────────────

enum Role             { STUDENT PARENT TEACHER ADMIN }
enum ContentStatus    { DRAFT IN_REVIEW PUBLISHED ARCHIVED }
enum Difficulty       { EASY MEDIUM HARD }
enum CognitiveLevel   { REMEMBER UNDERSTAND APPLY ANALYSE EVALUATE CREATE }
enum Importance       { HIGH MEDIUM LOW }
enum CompletionStatus { NOT_STARTED IN_PROGRESS COMPLETED }
enum SavedItemKind    { HIGHLIGHT SNIPPET BOOKMARK DOODLE PERSONAL_NOTE }
enum PracticeMode     { TOPIC CHAPTER MIXED TIMED ADAPTIVE MISTAKE }
enum AssessmentType   { DAILY_CHALLENGE CHAPTER WEEKLY MONTHLY GRAND ERROR OLYMPIAD FOUNDATION }
enum AssessmentState  { SCHEDULED IN_PROGRESS SUBMITTED EVALUATED ABANDONED }
enum AnswerOutcome    { CORRECT INCORRECT SKIPPED }
enum ErrorCategory    { CONCEPTUAL CALCULATION CARELESS TIME_MANAGEMENT }
enum RevisionPriority { CRITICAL HIGH MEDIUM LOW }
enum RevisionState    { PENDING SCHEDULED COMPLETED DISMISSED }
enum TaskType         { READ_TOPIC PRACTICE ASSESSMENT REVISION_PACK }
enum TaskState        { PENDING COMPLETED MISSED RESCHEDULED }
enum RecommendationKind {
  NEXT_CHAPTER REVISE_CONCEPT PRACTICE_QUESTIONS SUGGESTED_TEST
  DAILY_GOAL REVISION_PACK MOTIVATION
}
enum NotificationKind { REMINDER ALERT ACHIEVEMENT DIGEST }
enum QuestionKind     { MCQ_SINGLE MCQ_MULTI NUMERIC TRUE_FALSE SHORT_ANSWER }

// ─────────────────── identity, tenancy, roles ───────────────────

model Institution {
  id        String   @id @default(cuid())
  name      String
  code      String   @unique
  users     User[]
  classrooms Classroom[]
  createdAt DateTime @default(now())
}

model User {
  id             String   @id @default(cuid())
  email          String   @unique
  passwordHash   String
  role           Role
  fullName       String
  phoneEnc       String?              // app-layer encrypted (see assumptions)
  isActive       Boolean  @default(true)
  institutionId  String?
  institution    Institution? @relation(fields: [institutionId], references: [id])
  lastLoginAt    DateTime?
  createdAt      DateTime @default(now())
  updatedAt      DateTime @updatedAt

  studentProfile StudentProfile?
  refreshTokens  RefreshToken[]
  childLinks     ParentStudentLink[] @relation("parent")
  parentLinks    ParentStudentLink[] @relation("student")
  memberships    ClassroomMember[]
  auditLogs      AuditLog[]
  notifications  Notification[]

  @@index([role, institutionId])
}

model RefreshToken {
  id         String   @id @default(cuid())
  userId     String
  user       User     @relation(fields: [userId], references: [id], onDelete: Cascade)
  tokenHash  String   @unique        // SHA-256 of the token; raw value never stored
  familyId   String                  // rotation family, for reuse detection
  expiresAt  DateTime
  revokedAt  DateTime?
  userAgent  String?
  createdAt  DateTime @default(now())

  @@index([userId, expiresAt])
}

model StudentProfile {
  id            String   @id @default(cuid())
  userId        String   @unique
  user          User     @relation(fields: [userId], references: [id], onDelete: Cascade)
  classLevelId  String
  classLevel    ClassLevel @relation(fields: [classLevelId], references: [id])
  board         String?              // CBSE / ICSE / State
  dailyStudyMinutes Int   @default(90)
  timezone      String   @default("Asia/Kolkata")
  onboardedAt   DateTime?

  goals         Goal[]
  progress      TopicProgress[]
  savedItems    SavedItem[]
  practice      PracticeSession[]
  assessments   AssessmentResult[]
  attempts      QuestionAttempt[]
  revisionQueue RevisionQueueItem[]
  revisionPacks RevisionPack[]
  plans         DailyStudyPlan[]
  recommendations Recommendation[]
  mastery       TopicMastery[]
  studyDays     StudyDay[]
  streak        Streak?
  rewards       RewardLedger[]
  readiness     ReadinessSnapshot[]
}

model ParentStudentLink {
  id         String @id @default(cuid())
  parentId   String
  studentId  String
  parent     User   @relation("parent",  fields: [parentId],  references: [id], onDelete: Cascade)
  student    User   @relation("student", fields: [studentId], references: [id], onDelete: Cascade)
  relation   String @default("guardian")
  createdAt  DateTime @default(now())

  @@unique([parentId, studentId])
}

/// A teaching group (batch/section) — distinct from ClassLevel (grade).
model Classroom {
  id            String @id @default(cuid())
  institutionId String
  institution   Institution @relation(fields: [institutionId], references: [id])
  name          String
  classLevelId  String
  classLevel    ClassLevel @relation(fields: [classLevelId], references: [id])
  academicYear  String
  members       ClassroomMember[]
  createdAt     DateTime @default(now())

  @@unique([institutionId, name, academicYear])
}

model ClassroomMember {
  id          String    @id @default(cuid())
  classroomId String
  userId      String
  roleInClass Role                    // TEACHER or STUDENT
  classroom   Classroom @relation(fields: [classroomId], references: [id], onDelete: Cascade)
  user        User      @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@unique([classroomId, userId])
  @@index([userId])
}

// ────────────────── curriculum / syllabus intelligence ──────────────────

model ClassLevel {
  id        String @id @default(cuid())
  name      String @unique            // "Class 8", "Class 9", "Class 10"
  ordinal   Int    @unique
  subjects  Subject[]
  students  StudentProfile[]
  classrooms Classroom[]
}

model Subject {
  id           String @id @default(cuid())
  classLevelId String
  classLevel   ClassLevel @relation(fields: [classLevelId], references: [id])
  name         String
  slug         String
  colorToken   String?
  displayOrder Int    @default(0)
  chapters     Chapter[]

  @@unique([classLevelId, slug])
}

model Chapter {
  id            String @id @default(cuid())
  subjectId     String
  subject       Subject @relation(fields: [subjectId], references: [id], onDelete: Cascade)
  title         String
  slug          String
  displayOrder  Int     @default(0)
  importance    Importance @default(MEDIUM)
  weightage     Float   @default(0)     // % exam relevance — FR-28
  estimatedMinutes Int  @default(0)
  status        ContentStatus @default(DRAFT)
  sourceRef     String?                 // provenance from the extraction pipeline
  topics        Topic[]

  @@unique([subjectId, slug])
  @@index([subjectId, displayOrder])
}

model Topic {
  id            String @id @default(cuid())
  chapterId     String
  chapter       Chapter @relation(fields: [chapterId], references: [id], onDelete: Cascade)
  title         String
  slug          String
  displayOrder  Int     @default(0)
  importance    Importance @default(MEDIUM)
  weightage     Float   @default(0)
  estimatedMinutes Int  @default(15)
  difficulty    Difficulty @default(MEDIUM)
  conceptTags   String[]
  status        ContentStatus @default(DRAFT)

  note          Note?
  questions     Question[]
  prerequisites TopicPrerequisite[] @relation("dependent")
  dependents    TopicPrerequisite[] @relation("prerequisite")
  progress      TopicProgress[]
  savedItems    SavedItem[]
  mastery       TopicMastery[]
  revisionItems RevisionQueueItem[]

  @@unique([chapterId, slug])
  @@index([chapterId, displayOrder])
}

model TopicPrerequisite {
  id             String @id @default(cuid())
  topicId        String                        // this topic…
  prerequisiteId String                        // …requires this one first
  topic          Topic  @relation("dependent",    fields: [topicId],        references: [id], onDelete: Cascade)
  prerequisite   Topic  @relation("prerequisite", fields: [prerequisiteId], references: [id], onDelete: Cascade)

  @@unique([topicId, prerequisiteId])
}

// ─────────────────────────── notes & annotations ───────────────────────────

/// AI-generated study note for a topic. Body is structured JSON (blocks:
/// explanation, worked examples, formulae, tricks, common mistakes, summary)
/// so the reader can anchor highlights to stable block ids.
model Note {
  id            String @id @default(cuid())
  topicId       String @unique
  topic         Topic  @relation(fields: [topicId], references: [id], onDelete: Cascade)
  version       Int    @default(1)
  status        ContentStatus @default(DRAFT)
  body          Json
  plainText     String            // denormalised for full-text search
  readingMinutes Int   @default(0)
  generatedBy   String?           // model id, or null for imported content
  generatedAt   DateTime?
  reviewedById  String?
  reviewedAt    DateTime?
  createdAt     DateTime @default(now())
  updatedAt     DateTime @updatedAt

  revisions     NoteVersion[]

  @@index([status])
}

model NoteVersion {
  id        String   @id @default(cuid())
  noteId    String
  note      Note     @relation(fields: [noteId], references: [id], onDelete: Cascade)
  version   Int
  body      Json
  createdAt DateTime @default(now())

  @@unique([noteId, version])
}

/// One table for everything the Saved Library shows. `kind` discriminates;
/// chapter/topic/timestamp metadata is preserved on every row per the PRD's
/// developer note. See assumption A3 for why this isn't five tables.
model SavedItem {
  id          String   @id @default(cuid())
  studentId   String
  student     StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  kind        SavedItemKind
  topicId     String
  topic       Topic    @relation(fields: [topicId], references: [id], onDelete: Cascade)
  chapterId   String                     // denormalised: library filters by chapter
  noteVersion Int?                       // which note version was anchored to
  blockId     String?                    // anchor inside the note body
  startOffset Int?
  endOffset   Int?
  selectedText String?                   // snippet / highlight payload
  bodyText    String?                    // personal note payload
  strokes     Json?                      // doodle payload (vector strokes)
  color       String?
  tags        String[]
  createdAt   DateTime @default(now())
  updatedAt   DateTime @updatedAt

  @@index([studentId, kind, createdAt])
  @@index([studentId, chapterId])
  @@index([topicId])
}

/// Per-student reading state — powers "Continue Learning" and reading analytics.
model TopicProgress {
  id             String @id @default(cuid())
  studentId      String
  topicId        String
  student        StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  topic          Topic @relation(fields: [topicId], references: [id], onDelete: Cascade)
  status         CompletionStatus @default(NOT_STARTED)
  scrollPercent  Int    @default(0)
  secondsRead    Int    @default(0)
  firstOpenedAt  DateTime?
  lastOpenedAt   DateTime?
  completedAt    DateTime?

  @@unique([studentId, topicId])
  @@index([studentId, lastOpenedAt])
}

// ──────────────────── question bank & assessment engine ────────────────────

model Question {
  id               String @id @default(cuid())
  topicId          String
  topic            Topic  @relation(fields: [topicId], references: [id], onDelete: Cascade)
  subtopic         String?
  kind             QuestionKind @default(MCQ_SINGLE)
  stem             String
  solution         String?          // worked explanation shown after submit
  difficulty       Difficulty @default(MEDIUM)
  cognitiveLevel   CognitiveLevel @default(UNDERSTAND)
  learningObjective String?
  expectedSeconds  Int    @default(60)
  status           ContentStatus @default(DRAFT)
  dedupeHash       String?          // normalised-stem hash, blocks bank duplication
  sourceRef        String?
  createdAt        DateTime @default(now())

  options          QuestionOption[]
  attempts         QuestionAttempt[]
  assessmentLinks  AssessmentQuestion[]
  packItems        RevisionPackItem[]

  @@index([topicId, difficulty, status])
  @@index([dedupeHash])
}

model QuestionOption {
  id         String  @id @default(cuid())
  questionId String
  question   Question @relation(fields: [questionId], references: [id], onDelete: Cascade)
  label      String            // "A".."D"
  body       String
  isCorrect  Boolean @default(false)
  rationale  String?

  @@index([questionId])
}

model PracticeSession {
  id            String @id @default(cuid())
  studentId     String
  student       StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  mode          PracticeMode
  topicId       String?
  chapterId     String?
  targetCount   Int
  timeLimitSec  Int?
  startingDifficulty Difficulty @default(MEDIUM)
  endingDifficulty   Difficulty?
  correctCount  Int    @default(0)
  totalAnswered Int    @default(0)
  startedAt     DateTime @default(now())
  completedAt   DateTime?

  attempts      QuestionAttempt[]

  @@index([studentId, startedAt])
}

model Assessment {
  id            String @id @default(cuid())
  type          AssessmentType
  title         String
  classLevelId  String?
  subjectId     String?
  chapterId     String?
  durationSec   Int
  totalMarks    Int    @default(0)
  negativeMarking Float @default(0)
  scheduledFor  DateTime?
  createdById   String?              // teacher/admin, null for system-generated
  forStudentId  String?              // set for personalised Error Tests (FR-18)
  isSystemGenerated Boolean @default(false)
  createdAt     DateTime @default(now())

  questions     AssessmentQuestion[]
  results       AssessmentResult[]

  @@index([type, chapterId])
  @@index([forStudentId])
}

model AssessmentQuestion {
  id           String @id @default(cuid())
  assessmentId String
  questionId   String
  assessment   Assessment @relation(fields: [assessmentId], references: [id], onDelete: Cascade)
  question     Question   @relation(fields: [questionId],  references: [id])
  displayOrder Int
  marks        Int @default(1)

  @@unique([assessmentId, questionId])
}

model AssessmentResult {
  id             String @id @default(cuid())
  assessmentId   String
  studentId      String
  assessment     Assessment @relation(fields: [assessmentId], references: [id], onDelete: Cascade)
  student        StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  state          AssessmentState @default(IN_PROGRESS)
  score          Float  @default(0)
  maxScore       Float  @default(0)
  accuracyPct    Float  @default(0)
  correctCount   Int    @default(0)
  incorrectCount Int    @default(0)
  skippedCount   Int    @default(0)
  totalSeconds   Int    @default(0)
  /// Cached breakdowns for the result report (FR-17):
  /// { byTopic: [...], byDifficulty: {...}, byErrorCategory: {...} }
  breakdown      Json?
  aiFeedback     String?
  startedAt      DateTime @default(now())
  submittedAt    DateTime?
  evaluatedAt    DateTime?

  attempts       QuestionAttempt[]

  @@unique([assessmentId, studentId])
  @@index([studentId, submittedAt])
}

model QuestionAttempt {
  id                 String @id @default(cuid())
  studentId          String
  questionId         String
  student            StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  question           Question @relation(fields: [questionId], references: [id])
  practiceSessionId  String?
  assessmentResultId String?
  practiceSession    PracticeSession?  @relation(fields: [practiceSessionId],  references: [id], onDelete: Cascade)
  assessmentResult   AssessmentResult? @relation(fields: [assessmentResultId], references: [id], onDelete: Cascade)
  selectedOptionIds  String[]
  answerText         String?
  outcome            AnswerOutcome
  marksAwarded       Float  @default(0)
  seconds            Int    @default(0)
  confidence         Int?               // optional 1–5 self-rating
  answeredAt         DateTime @default(now())

  errorTags          AttemptErrorTag[]

  @@index([studentId, questionId, answeredAt])
  @@index([studentId, outcome])
}

model AttemptErrorTag {
  id         String @id @default(cuid())
  attemptId  String
  attempt    QuestionAttempt @relation(fields: [attemptId], references: [id], onDelete: Cascade)
  category   ErrorCategory
  confidence Float  @default(1)
  source     String @default("rule")   // "rule" | "ai"
  detail     String?

  @@unique([attemptId, category])
}

// ─────────────────────────── analytics ───────────────────────────

/// Append-only event log. Every meaningful interaction lands here first;
/// derived tables below are projections that handlers maintain.
model AnalyticsEvent {
  id          String   @id @default(cuid())
  eventName   String
  actorId     String
  studentId   String?
  subjectId   String?
  chapterId   String?
  topicId     String?
  payload     Json
  occurredAt  DateTime @default(now())
  processedAt DateTime?

  @@index([studentId, eventName, occurredAt])
  @@index([processedAt])
}

model TopicMastery {
  id             String @id @default(cuid())
  studentId      String
  topicId        String
  student        StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  topic          Topic @relation(fields: [topicId], references: [id], onDelete: Cascade)
  masteryScore   Float  @default(0)     // 0–100, see assumption A5
  accuracyPct    Float  @default(0)
  attemptCount   Int    @default(0)
  correctCount   Int    @default(0)
  consecutiveWrong Int  @default(0)
  avgSeconds     Float  @default(0)
  lastAttemptAt  DateTime?
  lastRevisedAt  DateTime?
  isWeak         Boolean @default(false)
  updatedAt      DateTime @updatedAt

  @@unique([studentId, topicId])
  @@index([studentId, isWeak])
}

/// One row per student per calendar day — powers consistency, streaks,
/// weekly progress, and parent "attendance to plan" reporting.
model StudyDay {
  id             String @id @default(cuid())
  studentId      String
  student        StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  day            DateTime @db.Date
  readingMinutes Int @default(0)
  practiceCount  Int @default(0)
  assessmentCount Int @default(0)
  revisionCount  Int @default(0)
  tasksPlanned   Int @default(0)
  tasksCompleted Int @default(0)
  accuracyPct    Float @default(0)

  @@unique([studentId, day])
}

/// Generic rollup cache for dashboard widgets and institutional analytics
/// (scope = STUDENT | CLASSROOM | INSTITUTION).
model MetricSnapshot {
  id         String   @id @default(cuid())
  scope      String
  scopeId    String
  metric     String
  periodStart DateTime
  periodEnd   DateTime
  value      Float
  detail     Json?
  computedAt DateTime @default(now())

  @@unique([scope, scopeId, metric, periodStart])
}

// ───────────────────── smart revision engine ─────────────────────

model RevisionQueueItem {
  id           String @id @default(cuid())
  studentId    String
  topicId      String
  student      StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  topic        Topic @relation(fields: [topicId], references: [id], onDelete: Cascade)
  priority     RevisionPriority
  state        RevisionState @default(PENDING)
  reason       String            // "repeated_incorrect" | "low_accuracy" | "stale" | "mastered_refresher"
  triggerRef   String?           // assessmentResultId / attemptId that caused it
  dueAt        DateTime
  repetition   Int    @default(0)   // spaced-repetition step index
  intervalDays Int    @default(1)
  completedAt  DateTime?
  createdAt    DateTime @default(now())

  packItems    RevisionPackItem[]

  @@unique([studentId, topicId, state])
  @@index([studentId, dueAt, priority])
}

model RevisionPack {
  id            String @id @default(cuid())
  studentId     String
  student       StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  title         String
  estimatedMinutes Int @default(12)
  aiSummary     String?
  generatedAt   DateTime @default(now())
  completedAt   DateTime?
  quizResultId  String?

  items         RevisionPackItem[]

  @@index([studentId, completedAt])
}

model RevisionPackItem {
  id           String @id @default(cuid())
  packId       String
  pack         RevisionPack @relation(fields: [packId], references: [id], onDelete: Cascade)
  queueItemId  String?
  queueItem    RevisionQueueItem? @relation(fields: [queueItemId], references: [id])
  savedItemId  String?
  questionId   String?
  question     Question? @relation(fields: [questionId], references: [id])
  kind         String            // "snippet" | "formula" | "wrong_question" | "summary" | "quiz"
  body         Json?
  displayOrder Int @default(0)

  @@index([packId, displayOrder])
}

// ───────────────────── goal planner ─────────────────────

model Goal {
  id            String @id @default(cuid())
  studentId     String
  student       StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  targetExam    String
  targetScore   Float?
  targetRank    Int?
  examDate      DateTime
  dailyStudyMinutes Int  @default(90)
  subjectFocus  String[]
  isActive      Boolean @default(true)
  createdAt     DateTime @default(now())

  plans         DailyStudyPlan[]
  readiness     ReadinessSnapshot[]

  @@index([studentId, isActive])
}

model DailyStudyPlan {
  id           String @id @default(cuid())
  studentId    String
  goalId       String?
  student      StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  goal         Goal?  @relation(fields: [goalId], references: [id])
  day          DateTime @db.Date
  plannedMinutes Int  @default(0)
  generatedAt  DateTime @default(now())
  regeneratedCount Int @default(0)

  tasks        DailyTask[]

  @@unique([studentId, day])
}

model DailyTask {
  id           String @id @default(cuid())
  planId       String
  plan         DailyStudyPlan @relation(fields: [planId], references: [id], onDelete: Cascade)
  type         TaskType
  title        String
  topicId      String?
  chapterId    String?
  assessmentId String?
  revisionPackId String?
  estimatedMinutes Int @default(20)
  state        TaskState @default(PENDING)
  displayOrder Int @default(0)
  completedAt  DateTime?
  rescheduledFromId String?     // chain when a missed task is moved forward

  @@index([planId, displayOrder])
}

model ReadinessSnapshot {
  id            String @id @default(cuid())
  studentId     String
  goalId        String
  student       StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  goal          Goal  @relation(fields: [goalId], references: [id], onDelete: Cascade)
  readinessPct  Float
  syllabusPct   Float
  accuracyPct   Float
  consistencyPct Float
  drivers       Json                // per-factor contributions, for explainability
  computedAt    DateTime @default(now())

  @@index([studentId, computedAt])
}

// ───────────────── recommendations, rewards, notifications ─────────────────

model Recommendation {
  id          String @id @default(cuid())
  studentId   String
  student     StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  kind        RecommendationKind
  title       String
  rationale   String              // the "why" — always shown to the student
  topicId     String?
  chapterId   String?
  assessmentId String?
  revisionPackId String?
  score       Float  @default(0)  // ranking weight
  source      String @default("rule")   // "rule" | "ai"
  validUntil  DateTime?
  actedOnAt   DateTime?
  dismissedAt DateTime?
  createdAt   DateTime @default(now())

  @@index([studentId, createdAt])
}

model Streak {
  id            String @id @default(cuid())
  studentId     String @unique
  student       StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  currentDays   Int @default(0)
  longestDays   Int @default(0)
  lastActiveDay DateTime? @db.Date
  freezesLeft   Int @default(0)
}

model RewardLedger {
  id        String @id @default(cuid())
  studentId String
  student   StudentProfile @relation(fields: [studentId], references: [id], onDelete: Cascade)
  kind      String            // "points" | "badge"
  code      String            // badge code or points reason
  points    Int    @default(0)
  earnedAt  DateTime @default(now())

  @@index([studentId, earnedAt])
}

model Notification {
  id        String @id @default(cuid())
  userId    String
  user      User   @relation(fields: [userId], references: [id], onDelete: Cascade)
  kind      NotificationKind
  title     String
  body      String
  linkTo    String?
  readAt    DateTime?
  sendAfter DateTime @default(now())
  sentAt    DateTime?
  createdAt DateTime @default(now())

  @@index([userId, readAt])
}

model AuditLog {
  id         String @id @default(cuid())
  actorId    String
  actor      User   @relation(fields: [actorId], references: [id])
  action     String
  entityType String
  entityId   String
  before     Json?
  after      Json?
  ip         String?
  createdAt  DateTime @default(now())

  @@index([entityType, entityId])
  @@index([actorId, createdAt])
}

model AiUsageLog {
  id         String @id @default(cuid())
  purpose    String
  model      String
  inputTokens  Int
  outputTokens Int
  latencyMs  Int
  ok         Boolean
  errorText  String?
  createdAt  DateTime @default(now())

  @@index([purpose, createdAt])
}
```

---

## Part C — Documented assumptions (will be mirrored in `PROGRESS.md`)

- **A1 — `Class` is split in two.** The PRD uses "Class" for both the
  curriculum grade (Class → Subject → Chapter → Topic) and the teaching group
  (`TeacherClassLink`). Modelled as `ClassLevel` (grade) and `Classroom`
  (batch/section) with a single `ClassroomMember` join table covering both
  `TeacherClassLink` and student enrolment.
- **A2 — `Institution` added.** Institutional analytics (FR-30) and
  "institution scale" need a tenant root; not in the entity list, but implied.
- **A3 — One `SavedItem` table, not five.** Highlight / Snippet / Bookmark /
  Doodle / PersonalNote share the same anchor (student, chapter, topic, note
  version, offsets, timestamp) and are always shown together in the Saved
  Library. Five tables would mean a 4–5 way UNION on the library's main query
  and duplicated metadata columns. Discriminated by `kind`; payload columns are
  nullable per kind and validated at the service boundary. **Easy to split
  later — say the word if you want the literal five models.**
- **A4 — `ErrorCategory` is an enum + `AttemptErrorTag` join**, not a table of
  rows. The four categories are fixed by the PRD; an attempt can carry more than
  one, each with a confidence and a source (rule vs AI).
- **A5 — Mastery score formula (placeholder, tunable):**
  `mastery = 100 × (0.6·accuracy + 0.25·recency + 0.15·speed)` where recency
  decays over 14 days and speed is `clamp(expectedSeconds / actualSeconds, 0, 1)`.
  `isWeak = mastery < 60 || consecutiveWrong ≥ 2`. Kept in
  `packages/shared/scoring.ts` so it's a one-file change.
- **A6 — Spaced-repetition intervals (placeholder):** SM-2-lite, per priority —
  CRITICAL `[0, 1, 3]` days, HIGH `[1, 3, 7]`, MEDIUM `[7, 14, 30]`,
  LOW `[30, 60]`. Mapped from the PRD's priority table (repeated incorrect →
  CRITICAL/immediate; accuracy <60% → HIGH/within 24h; no revision 7+ days →
  MEDIUM/weekly; mastered → LOW/monthly).
- **A7 — Readiness (FR-25) placeholder:**
  `readiness = 0.45·syllabusCoverage + 0.35·weightedAccuracy + 0.20·consistency`,
  weighted by chapter `weightage`. Stored with per-factor `drivers` so the UI can
  explain the number rather than just print it.
- **A8 — Adaptive difficulty (FR-16):** 3-band ladder. Two consecutive correct
  under expected time → step up; two consecutive incorrect → step down;
  otherwise hold. Deterministic, no AI call in the answer loop (keeps practice
  responsive).
- **A9 — Encryption.** Postgres at-rest encryption + TLS covers the NFR;
  additionally, directly-identifying non-searchable PII (phone) is encrypted at
  the application layer via a `KMS_KEY`-derived AES-256-GCM helper. Emails stay
  plaintext because login requires equality lookup.
- **A10 — REST, not GraphQL**, per your default.
- **A11 — Phase 1 ships `InProcessEventBus`**; `AnalyticsEvent` rows are written
  synchronously in the same transaction as the domain write, so no events are
  lost even before Redis exists.
