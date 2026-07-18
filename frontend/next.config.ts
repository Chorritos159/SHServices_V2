import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * `standalone`: al construir, Next copia en `.next/standalone` el servidor y
   * SOLO las dependencias que realmente usa, con su propio `server.js`.
   *
   * Es lo que permite que la imagen de producción no arrastre `node_modules`
   * entero (cientos de MB de dependencias de build que en runtime no hacen
   * falta). Sin esto, la imagen del frontend pesaría más que los 8
   * microservicios juntos.
   */
  output: "standalone",
};

export default nextConfig;
