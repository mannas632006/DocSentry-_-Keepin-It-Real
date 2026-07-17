import { useEffect, useState } from "react";

const LS_THEME = "docsentry.theme";

/** Theme: explicit choice wins, otherwise follow the OS.
 *  The initial value is applied in index.html before paint to avoid a flash. */
export function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem(LS_THEME) || "auto");

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") {
      root.removeAttribute("data-theme");
      localStorage.removeItem(LS_THEME);
    } else {
      root.setAttribute("data-theme", theme);
      localStorage.setItem(LS_THEME, theme);
    }
  }, [theme]);

  const cycle = () =>
    setTheme((t) => (t === "auto" ? "dark" : t === "dark" ? "light" : "auto"));

  return { theme, cycle };
}
