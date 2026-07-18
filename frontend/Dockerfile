# =====================================================================
#  Frontend (Next.js) — imagen de PRODUCCIÓN
#
#  Cierra la brecha #9: hasta ahora el frontend quedaba fuera de
#  docker-compose y había que levantarlo a mano con `npm run dev`, así que
#  el sistema NO se levantaba con un solo comando y además la web corría en
#  modo desarrollo (sin optimizar, con recarga en caliente) durante la
#  sustentación.
#
#  Tres etapas para que la imagen final lleve lo mínimo:
#    deps    -> instala dependencias (se cachea si package*.json no cambia)
#    builder -> compila el proyecto
#    runner  -> solo el servidor ya compilado, sin código fuente ni toolchain
# =====================================================================

# ---- 1. Dependencias -------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
# Solo los manifiestos: si el código cambia pero las dependencias no, Docker
# reutiliza esta capa y se ahorra el npm ci completo.
COPY package.json package-lock.json* ./
RUN npm ci

# ---- 2. Compilación --------------------------------------------------
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Next valida las variables en tiempo de BUILD para las páginas estáticas.
# Se dan valores de relleno: los reales llegan en runtime desde el compose,
# y `output: standalone` mantiene el render en servidor, así que ninguno de
# estos queda cocido en el bundle.
ENV GATEWAY_URL=http://api-gateway:80
ENV JWT_SECRET_KEY=build_time_placeholder
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ---- 3. Ejecución ----------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0

# Usuario sin privilegios: si alguien logra ejecutar algo dentro del
# contenedor, no lo hace como root (mismo criterio que los servicios Python).
RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

# `standalone` trae el server.js y solo las dependencias necesarias.
# `static` y `public` van aparte porque Next los sirve desde disco.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3001

# Healthcheck contra la página de login: comprueba que Next responde de
# verdad, no solo que el proceso exista.
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:3001/login',r=>process.exit(r.statusCode<400?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
