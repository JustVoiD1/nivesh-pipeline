"use client";

import { useEffect, useState } from "react";
import { Sun, Moon, Laptop } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTheme } from "next-themes";

export function ThemeToggle() {
  // const [theme, setTheme] = useState<"light" | "dark">("light");
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    // Read from localStorage on mount
    setMounted((prev) => true)
    const savedTheme = (localStorage.getItem("theme") as "light" | "dark") || "light";
    setTheme(savedTheme);
  }, []);

  const applyTheme = (newTheme: "light" | "dark") => {
    setTheme(newTheme);
    localStorage.setItem("theme", newTheme);

    // const root = document.documentElement;
    // if (newTheme === "dark") {
    //   root.classList.add("dark");
    // } else {
    //   root.classList.remove("dark");
    // }
  };

  const cycleTheme = () => {
    if (theme === "light") applyTheme("dark");
    else applyTheme("light");
  };

  const getIcon = () => {
    if (theme === "light") return <Sun className="h-[1.2rem] w-[1.2rem] text-amber-500 transition-all" />;
    if (theme === "dark") return <Moon className="h-[1.2rem] w-[1.2rem] text-indigo-400 transition-all" />;
  };

  if (!mounted) {
    return (
      <div className="w-9 h-9 border border-zinc-200 dark:border-zinc-800 rounded-md bg-transparent" />
    )
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="icon"
        onClick={cycleTheme}
        className="relative h-9 w-9 rounded-lg border-zinc-200 dark:border-zinc-800 transition-colors"
      >
        {getIcon()}
      </Button>
    </div>
  );
}
