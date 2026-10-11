import { type NextRequest, NextResponse } from "next/server";

// Optimistic auth check only: is there a session cookie at all? The authoritative check is
// FastAPI's get_current_user on every API call (the cookie may be expired or revoked).
// Per Next.js guidance, never hit a database or Redis from proxy: it runs on every route.
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has("sid");
  const onLogin = request.nextUrl.pathname === "/login";

  if (!hasSession && !onLogin) return NextResponse.redirect(new URL("/login", request.url));
  if (hasSession && onLogin) return NextResponse.redirect(new URL("/", request.url));
  return NextResponse.next();
}

export const config = {
  // Skip API calls (FastAPI does its own auth), Next internals, and static files.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|status).*)"],
};
