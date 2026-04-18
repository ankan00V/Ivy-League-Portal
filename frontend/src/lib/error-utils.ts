type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatFastApiValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail)) {
    return null;
  }

  const parts = detail
    .map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const msg = typeof item.msg === "string" ? item.msg : "";
      const locPath = Array.isArray(item.loc)
        ? item.loc
            .map((segment) => String(segment))
            .filter((segment) => segment.length > 0 && segment !== "body")
            .join(".")
        : "";
      if (!msg) {
        return locPath || null;
      }
      return locPath ? `${locPath}: ${msg}` : msg;
    })
    .filter((value): value is string => typeof value === "string" && value.length > 0);

  if (parts.length === 0) {
    return null;
  }
  return parts.slice(0, 3).join(" | ");
}

function unwrapMessage(value: unknown): string | null {
  if (typeof value === "string" && value.trim().length > 0) {
    return value.trim();
  }

  if (!isRecord(value)) {
    return null;
  }

  const detail = value.detail;
  if (typeof detail === "string" && detail.trim().length > 0) {
    return detail.trim();
  }

  const validationMessage = formatFastApiValidationDetail(detail);
  if (validationMessage) {
    return validationMessage;
  }

  const message = value.message;
  if (typeof message === "string" && message.trim().length > 0) {
    return message.trim();
  }

  const error = value.error;
  if (typeof error === "string" && error.trim().length > 0) {
    return error.trim();
  }

  if (isRecord(error)) {
    const nestedError = unwrapMessage(error);
    if (nestedError) {
      return nestedError;
    }
  }

  return null;
}

export function getApiErrorMessage(payload: unknown, fallback: string): string {
  return unwrapMessage(payload) || fallback;
}

export function getUnknownErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message.trim();
  }
  return unwrapMessage(error) || fallback;
}
