/**
 * Shared role vocabulary for "Current Role" and "Preferred Roles".
 *
 * Both fields were free text, so the same role arrived as "SDE", "sde",
 * "Software Dev" and "Software Engineer" and nothing downstream could group
 * them. Matching, recommendations and any future per-role analytics all need a
 * stable value, which means a shared list rather than two hand-typed ones.
 *
 * Grouped because a flat list of 150+ options is unusable in a <select>. Groups
 * lead with the ones an Indian student or early-career candidate actually picks.
 */

export type RoleOption = {
  label: string;
  group: string;
};

const SOFTWARE_ROLES = [
  "Software Engineer",
  "Backend Developer",
  "Frontend Developer",
  "Full Stack Developer",
  "Mobile App Developer",
  "Android Developer",
  "iOS Developer",
  "Game Developer",
  "Embedded Systems Engineer",
  "Firmware Engineer",
  "Systems Engineer",
  "Web Developer",
  "API Engineer",
  "Software Development Engineer in Test",
  "Engineering Intern",
];

const DATA_AI_ROLES = [
  "Data Scientist",
  "Data Analyst",
  "Data Engineer",
  "Machine Learning Engineer",
  "AI Engineer",
  "Research Engineer",
  "Research Scientist",
  "NLP Engineer",
  "Computer Vision Engineer",
  "MLOps Engineer",
  "Business Intelligence Analyst",
  "Quantitative Analyst",
  "Statistician",
  "Data Annotator",
];

const INFRA_ROLES = [
  "DevOps Engineer",
  "Site Reliability Engineer",
  "Cloud Engineer",
  "Platform Engineer",
  "Infrastructure Engineer",
  "Database Administrator",
  "Network Engineer",
  "Security Engineer",
  "Security Analyst",
  "Penetration Tester",
  "IT Support Engineer",
];

const PRODUCT_DESIGN_ROLES = [
  "Product Manager",
  "Associate Product Manager",
  "Product Analyst",
  "Product Designer",
  "UX Designer",
  "UI Designer",
  "UX Researcher",
  "Graphic Designer",
  "Visual Designer",
  "Motion Designer",
  "Design Intern",
  "Technical Writer",
];

const BUSINESS_ROLES = [
  "Business Analyst",
  "Business Development Executive",
  "Management Consultant",
  "Strategy Analyst",
  "Operations Analyst",
  "Operations Manager",
  "Project Manager",
  "Program Manager",
  "Supply Chain Analyst",
  "Procurement Analyst",
];

const FINANCE_ROLES = [
  "Financial Analyst",
  "Investment Banking Analyst",
  "Equity Research Analyst",
  "Risk Analyst",
  "Accountant",
  "Auditor",
  "Actuarial Analyst",
  "Credit Analyst",
  "Treasury Analyst",
  "Finance Intern",
];

const MARKETING_ROLES = [
  "Marketing Executive",
  "Digital Marketing Executive",
  "Content Writer",
  "Content Strategist",
  "SEO Specialist",
  "Social Media Manager",
  "Brand Manager",
  "Growth Marketer",
  "Performance Marketing Analyst",
  "Public Relations Executive",
  "Marketing Intern",
];

const SALES_SUPPORT_ROLES = [
  "Sales Executive",
  "Inside Sales Associate",
  "Account Manager",
  "Customer Success Manager",
  "Customer Support Executive",
  "Solutions Engineer",
  "Pre-Sales Consultant",
];

const CORE_ENGINEERING_ROLES = [
  "Mechanical Engineer",
  "Civil Engineer",
  "Electrical Engineer",
  "Electronics Engineer",
  "Chemical Engineer",
  "Aerospace Engineer",
  "Automotive Engineer",
  "Biomedical Engineer",
  "Industrial Engineer",
  "Manufacturing Engineer",
  "Quality Engineer",
  "Design Engineer",
  "Structural Engineer",
  "Site Engineer",
];

const HEALTH_SCIENCE_ROLES = [
  "Medical Intern",
  "Clinical Research Associate",
  "Pharmacist",
  "Biotechnologist",
  "Lab Technician",
  "Nurse",
  "Physiotherapist",
  "Nutritionist",
  "Public Health Analyst",
];

const LAW_POLICY_ROLES = [
  "Legal Associate",
  "Legal Intern",
  "Corporate Counsel",
  "Compliance Analyst",
  "Policy Analyst",
  "Paralegal",
  "Company Secretary",
];

const EDUCATION_SOCIAL_ROLES = [
  "Teacher",
  "Teaching Assistant",
  "Academic Tutor",
  "Instructional Designer",
  "Curriculum Developer",
  "Research Assistant",
  "Social Impact Associate",
  "NGO Program Associate",
];

const HR_ADMIN_ROLES = [
  "Human Resources Executive",
  "Talent Acquisition Specialist",
  "Recruiter",
  "HR Intern",
  "Office Administrator",
  "Executive Assistant",
];

const MEDIA_ROLES = [
  "Journalist",
  "Video Editor",
  "Photographer",
  "Animator",
  "Copywriter",
  "Podcast Producer",
  "Community Manager",
];

const STUDENT_ROLES = [
  "Student",
  "Fresher",
  "Intern",
  "Research Intern",
  "Freelancer",
  "Founder",
  "Co-Founder",
  "Open Source Contributor",
];

const GROUPED: Array<[string, string[]]> = [
  ["Student & Early Career", STUDENT_ROLES],
  ["Software Engineering", SOFTWARE_ROLES],
  ["Data, AI & Research", DATA_AI_ROLES],
  ["Infrastructure & Security", INFRA_ROLES],
  ["Product & Design", PRODUCT_DESIGN_ROLES],
  ["Business & Operations", BUSINESS_ROLES],
  ["Finance & Accounting", FINANCE_ROLES],
  ["Marketing & Content", MARKETING_ROLES],
  ["Sales & Customer", SALES_SUPPORT_ROLES],
  ["Core Engineering", CORE_ENGINEERING_ROLES],
  ["Healthcare & Life Sciences", HEALTH_SCIENCE_ROLES],
  ["Law & Policy", LAW_POLICY_ROLES],
  ["Education & Social Impact", EDUCATION_SOCIAL_ROLES],
  ["Human Resources & Admin", HR_ADMIN_ROLES],
  ["Media & Creative", MEDIA_ROLES],
];

export const ROLE_OPTIONS: RoleOption[] = GROUPED.flatMap(([group, roles]) =>
  roles.map((label) => ({ label, group })),
);

export const ROLE_GROUPS: string[] = GROUPED.map(([group]) => group);

const ROLE_BY_NORMALIZED = new Map<string, string>(
  ROLE_OPTIONS.map((option) => [option.label.trim().toLowerCase(), option.label]),
);

/**
 * Resolve a stored value back to its canonical label.
 *
 * Existing rows were uppercased on save, so "SOFTWARE ENGINEER" has to map back
 * to "Software Engineer" or a <select> matches no option and renders blank.
 * Returns "" when the value is not in the taxonomy, which callers treat as
 * "Other" rather than discarding what the student typed.
 */
export function findKnownRole(value: string): string {
  return ROLE_BY_NORMALIZED.get(value.trim().toLowerCase()) ?? "";
}

export function splitRoles(value: string): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  value
    .split(",")
    .map((item) => item.trim())
    .forEach((item) => {
      if (!item) {
        return;
      }
      const key = item.toLowerCase();
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      // Store the canonical spelling when we recognise it, so the same role does
      // not persist as four different strings across four students.
      output.push(findKnownRole(item) || item);
    });
  return output;
}

export function joinRoles(values: string[]): string {
  return values.map((item) => item.trim()).filter(Boolean).join(", ");
}
