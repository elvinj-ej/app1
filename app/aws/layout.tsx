import { AuthProvider } from "@/components/aws/AuthProvider";
import { Sidebar } from "@/components/aws/Sidebar";

export const metadata = { title: "AWS Consumption Tracker — Cochlear" };

export default function AwsLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className="flex min-h-screen bg-gray-50">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">{children}</div>
      </div>
    </AuthProvider>
  );
}
