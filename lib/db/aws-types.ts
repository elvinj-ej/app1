export interface Workload {
  id: number;
  name: string;
  owner_user_id: string | null;
  owner_name: string | null;
  owner_email: string | null;
  aws_account_id: string | null;
  category: string | null;
  is_active: boolean;
  created_at: string;
}

export interface WorkloadMonthly {
  id: number;
  workload_id: number;
  fy_year: number;
  month_in_fy: number;
  cur_amount: number;
  forecast_amount: number;
  invoiced_amount: number | null;
  networking_share: number;
  invoice_adjustment_share: number;
  status: "forecast" | "invoiced";
  updated_at: string;
}

export interface NetworkingCost {
  id: number;
  fy_year: number;
  month_in_fy: number;
  description: string | null;
  amount: number;
  created_at: string;
}

export interface InvoiceAdjustment {
  id: number;
  fy_year: number;
  month_in_fy: number;
  amount: number;
  description: string | null;
  created_at: string;
}

export interface WorkloadConsumption {
  id: number;
  workload_id: number;
  workload_name: string;
  owner_name: string | null;
  owner_email: string | null;
  owner_user_id: string | null;
  category: string | null;
  fy_year: number;
  month_in_fy: number;
  calendar_year: number;
  calendar_month: number;
  cur_amount: number;
  forecast_amount: number;
  invoiced_amount: number | null;
  networking_share: number;
  invoice_adjustment_share: number;
  status: "forecast" | "invoiced";
  effective_total: number;
}

export interface Profile {
  id: string;
  display_name: string | null;
  email: string | null;
  role: "admin" | "user";
  created_at: string;
}

/** FY month labels: 1=July ... 12=June */
export const FY_MONTH_LABELS: Record<number, string> = {
  1: "Jul", 2: "Aug", 3: "Sep", 4: "Oct", 5: "Nov", 6: "Dec",
  7: "Jan", 8: "Feb", 9: "Mar", 10: "Apr", 11: "May", 12: "Jun",
};

/** Return the current FY year (year July starts). FY26 = July 2025 → fy_year 2025 */
export function currentFyYear(): number {
  const now = new Date();
  const m = now.getMonth() + 1; // 1-12
  const y = now.getFullYear();
  return m >= 7 ? y : y - 1;
}

/** Return month_in_fy (1=Jul) for a given calendar month (1=Jan) */
export function calMonthToFy(calMonth: number): number {
  return calMonth >= 7 ? calMonth - 6 : calMonth + 6;
}

/** Return calendar month for a given month_in_fy */
export function fyMonthToCalMonth(monthInFy: number): number {
  return monthInFy <= 6 ? monthInFy + 6 : monthInFy - 6;
}
