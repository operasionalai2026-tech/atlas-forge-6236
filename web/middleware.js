import { NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";

// Refresh sesi + proteksi rute: belum login → dilempar ke /login.
export async function middleware(request) {
  let response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Kalau env belum di-set (mis. lupa di Vercel), JANGAN crash-kan seluruh situs.
  // Lewatkan request supaya halaman tetap termuat & mudah didiagnosa.
  if (!url || !key) {
    console.error(
      "[middleware] NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY belum di-set."
    );
    return response;
  }

  try {
    const supabase = createServerClient(url, key, {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    });

    const {
      data: { user },
    } = await supabase.auth.getUser();

    const path = request.nextUrl.pathname;
    const isAuthPage = path.startsWith("/login");

    if (!user && !isAuthPage) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
    if (user && isAuthPage) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return response;
  } catch (e) {
    // Error auth transient tidak boleh menjatuhkan seluruh situs (500).
    console.error("[middleware] auth error:", e?.message || e);
    return response;
  }
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
