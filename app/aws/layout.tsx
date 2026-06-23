import { AuthProvider } from "@/components/aws/AuthProvider";
import { NavBar } from "@/components/aws/NavBar";

export const metadata = { title: "AWS Consumption Tracker" };

export default function AwsLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className="min-h-screen bg-gray-50 flex flex-col">
        <NavBar />
        <main className="flex-1 p-6 max-w-7xl mx-auto w-full">{children}</main>
      </div>
    </AuthProvider>
  );
}
