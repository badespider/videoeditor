import { UserRole } from "@prisma/client";

import { SidebarNavItem } from "types";

export const sidebarLinks: SidebarNavItem[] = [
  {
    title: "VIDEO EDITOR",
    items: [
      { href: "/dashboard", icon: "dashboard", title: "Dashboard" },
      { href: "/dashboard/jobs", icon: "play", title: "Video Jobs" },
      { href: "/dashboard/jobs/new", icon: "add", title: "New Video" },
    ],
  },
  {
    title: "ACCOUNT",
    items: [
      {
        href: "/dashboard/billing",
        icon: "billing",
        title: "Billing",
        authorizeOnly: UserRole.USER,
      },
      { href: "/dashboard/settings", icon: "settings", title: "Settings" },
    ],
  },
  {
    title: "ADMIN",
    items: [
      {
        href: "/admin",
        icon: "laptop",
        title: "Admin Panel",
        authorizeOnly: UserRole.ADMIN,
      },
      {
        href: "/dashboard/charts",
        icon: "lineChart",
        title: "Analytics",
        authorizeOnly: UserRole.ADMIN,
      },
    ],
  },
  {
    title: "HELP",
    items: [
      { href: "/", icon: "home", title: "Homepage" },
      { href: "/docs", icon: "bookOpen", title: "Documentation" },
    ],
  },
];
