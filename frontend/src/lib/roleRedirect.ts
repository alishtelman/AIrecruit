import type { User } from "@/lib/types";

export function getDefaultRouteForRole(role: User["role"]) {
  switch (role) {
    case "candidate":
      return "/candidate/dashboard";
    case "company_admin":
    case "company_member":
      return "/company/dashboard";
    case "platform_admin":
      return "/admin/dashboard";
    default:
      return "/";
  }
}
