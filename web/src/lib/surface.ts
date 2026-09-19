/** Which top-level surface a path belongs to. Moving between surfaces (landing, sign-in, the app) runs the
    full-screen loader; moving inside one animates only the part that changes. */
export function surface(path: string): string {
  if (path.startsWith("/app")) return "app";
  return path === "/" ? "home" : "auth";
}
