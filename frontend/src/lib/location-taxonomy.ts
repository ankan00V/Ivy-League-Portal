/**
 * Shared location vocabulary for "Preferred Work Locations".
 *
 * The field was free text, so the same place arrived as "Bangalore",
 * "Bengaluru", "bengaluru" and "Bengaluru-VTP". A scan of the live corpus found
 * 162 distinct location tokens across ~1,000 active opportunities, with
 * Bangalore and Bengaluru both present as separate values. Nothing downstream
 * could match a student's preference against a listing reliably.
 *
 * The list is grounded in what the corpus actually carries: India-dominant with
 * a real US/UK/Canada tail, plus the work-mode options students pick first.
 * Aliases collapse the common spelling splits onto one canonical label.
 */

export type LocationOption = {
  label: string;
  group: string;
};

const WORK_MODES = [
  "Remote",
  "Hybrid",
  "On-site",
  "Anywhere in India",
  "Open to Relocate",
];

// The metros that carry most Indian early-career hiring.
const METROS = [
  "Bengaluru",
  "Mumbai",
  "Delhi",
  "Gurugram",
  "Noida",
  "Hyderabad",
  "Pune",
  "Chennai",
  "Kolkata",
  "Ahmedabad",
];

const TIER_TWO_CITIES = [
  "Jaipur",
  "Indore",
  "Chandigarh",
  "Kochi",
  "Coimbatore",
  "Bhubaneswar",
  "Lucknow",
  "Nagpur",
  "Surat",
  "Vadodara",
  "Visakhapatnam",
  "Bhopal",
  "Thiruvananthapuram",
  "Mysuru",
  "Mangaluru",
  "Nashik",
  "Guwahati",
  "Dehradun",
  "Raipur",
  "Ranchi",
  "Patna",
  "Kanpur",
  "Ludhiana",
  "Amritsar",
  "Madurai",
  "Vijayawada",
  "Belagavi",
  "Goa",
];

const INDIAN_STATES = [
  "Andhra Pradesh",
  "Assam",
  "Bihar",
  "Chhattisgarh",
  "Delhi NCR",
  "Gujarat",
  "Haryana",
  "Himachal Pradesh",
  "Jharkhand",
  "Karnataka",
  "Kerala",
  "Madhya Pradesh",
  "Maharashtra",
  "Odisha",
  "Punjab",
  "Rajasthan",
  "Tamil Nadu",
  "Telangana",
  "Uttar Pradesh",
  "Uttarakhand",
  "West Bengal",
];

const INTERNATIONAL = [
  "United States",
  "United Kingdom",
  "Canada",
  "Germany",
  "Netherlands",
  "Ireland",
  "Singapore",
  "United Arab Emirates",
  "Australia",
  "Japan",
  "Switzerland",
  "France",
];

const GROUPED: Array<[string, string[]]> = [
  ["Work Mode", WORK_MODES],
  ["Metro Cities", METROS],
  ["Other Indian Cities", TIER_TWO_CITIES],
  ["States & Regions", INDIAN_STATES],
  ["International", INTERNATIONAL],
];

export const LOCATION_OPTIONS: LocationOption[] = GROUPED.flatMap(([group, places]) =>
  places.map((label) => ({ label, group })),
);

export const LOCATION_GROUPS: string[] = GROUPED.map(([group]) => group);

/**
 * Spelling variants that must collapse onto one canonical label.
 *
 * Keys are lowercased. Bangalore/Bengaluru and Gurgaon/Gurugram are the two
 * that actually appear split in the corpus today; the rest are the renames a
 * student is likely to type from memory.
 */
const LOCATION_ALIASES: Record<string, string> = {
  bangalore: "Bengaluru",
  bengaluru: "Bengaluru",
  blr: "Bengaluru",
  gurgaon: "Gurugram",
  gurugram: "Gurugram",
  bombay: "Mumbai",
  madras: "Chennai",
  calcutta: "Kolkata",
  trivandrum: "Thiruvananthapuram",
  mysore: "Mysuru",
  mangalore: "Mangaluru",
  baroda: "Vadodara",
  pondicherry: "Puducherry",
  vizag: "Visakhapatnam",
  ncr: "Delhi NCR",
  "new delhi": "Delhi",
  usa: "United States",
  us: "United States",
  uk: "United Kingdom",
  uae: "United Arab Emirates",
  wfh: "Remote",
  "work from home": "Remote",
};

const LOCATION_BY_NORMALIZED = new Map<string, string>(
  LOCATION_OPTIONS.map((option) => [option.label.trim().toLowerCase(), option.label]),
);

/**
 * Resolve a stored value to its canonical label, or "" when unrecognised.
 *
 * Existing rows were uppercased on save, so "BENGALURU" has to map back to
 * "Bengaluru" or a <select> matches no option. Returns "" rather than guessing,
 * so callers can keep whatever the student typed instead of discarding it.
 */
export function findKnownLocation(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return "";
  }
  return LOCATION_ALIASES[normalized] ?? LOCATION_BY_NORMALIZED.get(normalized) ?? "";
}

export function splitLocations(value: string): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  value
    .split(",")
    .map((item) => item.trim())
    .forEach((item) => {
      if (!item) {
        return;
      }
      // Canonicalise before the duplicate check, so "Bangalore, Bengaluru"
      // collapses to one chip instead of two chips for the same city.
      const canonical = findKnownLocation(item) || item;
      const key = canonical.toLowerCase();
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      output.push(canonical);
    });
  return output;
}

export function joinLocations(values: string[]): string {
  return values.map((item) => item.trim()).filter(Boolean).join(", ");
}
