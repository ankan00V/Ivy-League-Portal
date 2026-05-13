export type PasswordRequirement = {
  key: string;
  label: string;
  met: boolean;
};

export type PasswordStrength = {
  score: number;
  label: string;
  percent: number;
  color: string;
  requirements: PasswordRequirement[];
  acceptable: boolean;
};

export function evaluatePasswordStrength(password: string): PasswordStrength {
  const value = password || "";
  const requirements: PasswordRequirement[] = [
    { key: "length", label: "8+ characters", met: value.length >= 8 },
    { key: "lowercase", label: "Lowercase letter", met: /[a-z]/.test(value) },
    { key: "uppercase", label: "Uppercase letter", met: /[A-Z]/.test(value) },
    { key: "number", label: "Number", met: /\d/.test(value) },
    { key: "symbol", label: "Symbol for stronger security", met: /[^A-Za-z0-9]/.test(value) },
  ];
  const score = requirements.filter((item) => item.met).length;
  const label = score >= 5 ? "Strong" : score >= 4 ? "Good" : score >= 3 ? "Fair" : "Weak";
  const color = score >= 5 ? "#16a34a" : score >= 4 ? "#65a30d" : score >= 3 ? "#d97706" : "#dc2626";

  return {
    score,
    label,
    percent: Math.max(8, (score / requirements.length) * 100),
    color,
    requirements,
    acceptable: requirements.slice(0, 4).every((item) => item.met),
  };
}
