import {
  getDashboard,
  getOrgStructure,
  getStudentProfile,
  getStudentSubjectTopics,
  getSubjects,
  getTopics,
} from "@/lib/api";

function pickTopicName(
  topics: Array<{ id: string; topic_name?: string }>,
  topicId: string
): string | null {
  const name = topics.find((t) => t.id === topicId)?.topic_name?.trim();
  return name || null;
}

/** Resolve display name for a learn-session topic (best-effort, multiple sources). */
export async function resolveTopicTitle(
  token: string,
  topicId: string,
  options: {
    subjectId?: string | null;
    isInstitution?: boolean;
    urlTopicName?: string | null;
  } = {}
): Promise<string | null> {
  const urlName = options.urlTopicName?.trim();
  if (urlName) return urlName;

  const subjectId = options.subjectId?.trim();
  if (subjectId) {
    try {
      const topics = options.isInstitution
        ? await getStudentSubjectTopics(token, subjectId)
        : await getTopics(token, subjectId);
      const name = pickTopicName(topics, topicId);
      if (name) return name;
    } catch {
      /* fall through */
    }
  }

  try {
    const dashboard = await getDashboard(token);
    const name = pickTopicName(dashboard.recent_topics ?? [], topicId);
    if (name) return name;
  } catch {
    /* fall through */
  }

  try {
    if (options.isInstitution) {
      const [structure, profile] = await Promise.all([
        getOrgStructure(token),
        getStudentProfile(token),
      ]);
      const classId = profile.class_id?.trim();
      const cls =
        structure.classes.find((c) => c.id === classId) ??
        structure.classes[0];
      for (const sub of cls?.subjects ?? []) {
        const topics = await getStudentSubjectTopics(token, sub.id);
        const name = pickTopicName(topics, topicId);
        if (name) return name;
      }
    } else {
      const subjects = await getSubjects(token);
      for (const sub of subjects) {
        const topics = await getTopics(token, sub.id);
        const name = pickTopicName(topics, topicId);
        if (name) return name;
      }
    }
  } catch {
    /* noop */
  }

  return null;
}
