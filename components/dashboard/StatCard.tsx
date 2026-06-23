import { Card, CardTitle } from "@/components/ui/card";
import { LucideIcon } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string | number;
  unit?: string;
  sub?: string;
  icon: LucideIcon;
  color: string;   // tailwind bg color e.g. "bg-orange-50"
  iconColor: string; // tailwind text color e.g. "text-orange-500"
}

export function StatCard({ title, value, unit, sub, icon: Icon, color, iconColor }: StatCardProps) {
  return (
    <Card>
      <div className="flex items-start justify-between">
        <div>
          <CardTitle>{title}</CardTitle>
          <div className="flex items-end gap-1">
            <span className="text-3xl font-bold text-gray-800">{value}</span>
            {unit && <span className="text-sm text-gray-400 mb-1">{unit}</span>}
          </div>
          {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
        </div>
        <div className={`${color} p-2.5 rounded-xl`}>
          <Icon className={`w-5 h-5 ${iconColor}`} />
        </div>
      </div>
    </Card>
  );
}
