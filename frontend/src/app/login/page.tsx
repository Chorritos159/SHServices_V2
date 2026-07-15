import LoginForm from "@/components/LoginForm";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-sky-600 text-lg font-bold text-white">
            SH
          </div>
          <h1 className="text-2xl font-bold text-white">SHServices V2</h1>
          <p className="mt-1 text-sm text-slate-400">Ingresa con tus credenciales</p>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl backdrop-blur">
          <LoginForm />
        </div>

        <p className="mt-6 text-center text-xs text-slate-600">
          Demo: <span className="text-slate-400">admin/admin123</span> ·{" "}
          <span className="text-slate-400">caja01/caja123</span> ·{" "}
          <span className="text-slate-400">tecnico01/tecnico123</span>
        </p>
      </div>
    </main>
  );
}
