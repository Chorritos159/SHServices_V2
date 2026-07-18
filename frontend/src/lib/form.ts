/**
 * Lectura segura de campos de un `FormData`.
 *
 * `FormData.get()` devuelve `string | File | null`. Envolverlo en `String(...)`
 * compila y parece correcto, pero si el valor fuese un `File` el resultado
 * sería la cadena literal `"[object File]"` — un dato basura que viajaría al
 * backend sin que nadie se entere hasta ver el registro guardado.
 *
 * Estas funciones tratan ese caso explícitamente en vez de esconderlo.
 */

/** Texto de un campo. Si no llegó, o llegó un archivo, devuelve el respaldo. */
export function campoTexto(fd: FormData, nombre: string, respaldo = ""): string {
  const valor = fd.get(nombre);
  return typeof valor === "string" ? valor : respaldo;
}

/** Número de un campo. Si no es un número válido, devuelve el respaldo. */
export function campoNumero(fd: FormData, nombre: string, respaldo = 0): number {
  const texto = campoTexto(fd, nombre).trim();
  if (texto === "") return respaldo;
  const n = Number(texto);
  return Number.isFinite(n) ? n : respaldo;
}
