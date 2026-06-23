/**
 * Garmin Connect integration via the `garth` Python-style approach replicated in JS.
 * Uses Garmin's unofficial Connect API (same endpoints the app uses).
 *
 * Required env vars:
 *   GARMIN_EMAIL, GARMIN_PASSWORD
 *
 * Garmin does not have a public OAuth API for individuals — the session cookie
 * approach is the standard community solution (used by garth, garminconnect, etc).
 */

import axios, { AxiosInstance } from "axios";

const GARMIN_SSO_URL = "https://sso.garmin.com/sso";
const GARMIN_CONNECT_URL = "https://connect.garmin.com";

interface GarminDailySummary {
  calendarDate: string;
  totalKilocalories: number;
  activeKilocalories: number;
  bmrKilocalories: number;
  totalSteps: number;
  totalDistanceMeters: number;
  averageHeartRateInBeatsPerMinute: number | null;
}

interface GarminWeightMeasurement {
  date: string;
  weight: number; // grams
  bmi: number | null;
}

class GarminClient {
  private client: AxiosInstance;
  private cookies: string = "";

  constructor() {
    this.client = axios.create({
      baseURL: GARMIN_CONNECT_URL,
      headers: { "NK": "NT", "X-app-ver": "4.61.2.0" },
    });
  }

  async login(email: string, password: string): Promise<void> {
    // Step 1: get CSRF token
    const loginPage = await axios.get(`${GARMIN_SSO_URL}/signin`, {
      params: { service: "https://connect.garmin.com/modern" },
      withCredentials: true,
    });
    const csrfMatch = loginPage.data.match(/name="_csrf"\s+value="([^"]+)"/);
    const csrf = csrfMatch?.[1] ?? "";
    const setCookies = loginPage.headers["set-cookie"] ?? [];
    const sessionCookies = setCookies.map((c: string) => c.split(";")[0]).join("; ");

    // Step 2: submit credentials
    const loginResp = await axios.post(
      `${GARMIN_SSO_URL}/signin`,
      new URLSearchParams({
        username: email,
        password,
        _csrf: csrf,
        embed: "false",
        service: "https://connect.garmin.com/modern",
      }),
      {
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          Cookie: sessionCookies,
          Origin: "https://sso.garmin.com",
          Referer: `${GARMIN_SSO_URL}/signin`,
        },
        maxRedirects: 0,
        validateStatus: (s) => s < 400,
        withCredentials: true,
      }
    );

    const allCookies = [
      ...setCookies,
      ...(loginResp.headers["set-cookie"] ?? []),
    ].map((c: string) => c.split(";")[0]);
    this.cookies = [...new Set(allCookies)].join("; ");
    this.client.defaults.headers["Cookie"] = this.cookies;
  }

  async getDailySummary(date: string): Promise<GarminDailySummary> {
    const resp = await this.client.get(
      `/modern/proxy/usersummary-service/usersummary/daily/${date}`,
      { params: { calendarDate: date } }
    );
    return resp.data;
  }

  async getDailySummaryRange(
    startDate: string,
    endDate: string
  ): Promise<GarminDailySummary[]> {
    const resp = await this.client.get(
      `/modern/proxy/usersummary-service/usersummary/daily/range/${startDate}/${endDate}`
    );
    return resp.data;
  }

  async getWeightMeasurements(
    startDate: string,
    endDate: string
  ): Promise<GarminWeightMeasurement[]> {
    const resp = await this.client.get(
      `/modern/proxy/weight-service/weight/dateRange`,
      { params: { startDate, endDate } }
    );
    return (resp.data?.dateWeightList ?? []).map((entry: Record<string, unknown>) => ({
      date: entry.calendarDate,
      weight: entry.weight, // grams — divide by 1000 for kg
      bmi: entry.bmi ?? null,
    }));
  }
}

let _client: GarminClient | null = null;

async function getGarminClient(): Promise<GarminClient> {
  if (_client) return _client;
  const email = process.env.GARMIN_EMAIL;
  const password = process.env.GARMIN_PASSWORD;
  if (!email || !password) throw new Error("GARMIN_EMAIL and GARMIN_PASSWORD must be set");
  _client = new GarminClient();
  await _client.login(email, password);
  return _client;
}

export { getGarminClient };
export type { GarminDailySummary, GarminWeightMeasurement };
