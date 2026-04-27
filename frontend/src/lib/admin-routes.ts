export const ADMIN_LOGIN_PATH =
  (process.env.NEXT_PUBLIC_ADMIN_LOGIN_PATH || "/control/auth").trim() || "/control/auth";

export const ADMIN_DASHBOARD_PATH =
  (process.env.NEXT_PUBLIC_ADMIN_DASHBOARD_PATH || "/control/ops").trim() || "/control/ops";
