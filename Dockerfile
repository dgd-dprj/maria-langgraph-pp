# API Pessoa Presa (LangGraph nativo) — ponte Tykhe↔Verde.
FROM node:22-alpine AS base
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app
# minimum-release-age (proteção supply-chain do pnpm recente) rejeita pacotes
# publicados há poucas horas — o lockfile deste repo tem deps @langchain/aws
# atualizadas no mesmo dia. Desliga só aqui (build), não é config local. Fica
# no stage base pra valer em deps E build (cada stage tem seu próprio
# $HOME/.npmrc, não herda do stage anterior só por COPY de node_modules).
RUN pnpm config set minimum-release-age 0

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts

# node_modules separado, só com dependencies (sem typescript/tsx/etc) — é o
# que vai pro runner. Independente do stage `build` (não usa nada dele), o
# BuildKit roda os dois em paralelo.
FROM base AS deps-prod
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts --prod

FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM base AS runner
ENV NODE_ENV=production
COPY --from=deps-prod /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
EXPOSE 3001
CMD ["node", "dist/server.js"]
