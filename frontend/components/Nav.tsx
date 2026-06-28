"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/knowledge-base", label: "Knowledge Base" },
  { href: "/triples", label: "Triples" },
  { href: "/jobs", label: "Jobs" },
  { href: "/model", label: "Model" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="border-b border-gray-200 bg-white px-6 py-3 flex items-center gap-8">
      <span className="font-semibold text-gray-900 mr-4">SLM Platform</span>
      {links.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className={`text-sm font-medium transition-colors ${
            pathname.startsWith(l.href)
              ? "text-blue-600"
              : "text-gray-600 hover:text-gray-900"
          }`}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
