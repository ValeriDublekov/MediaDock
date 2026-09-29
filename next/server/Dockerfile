FROM node:22-alpine AS web-build
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY server/ ./server/
RUN dotnet restore server/src/MediaDock.Api/MediaDock.Api.csproj
RUN dotnet restore server/src/MediaDock.Worker/MediaDock.Worker.csproj
COPY --from=web-build /src/web/dist/ ./server/src/MediaDock.Api/wwwroot/
RUN dotnet publish server/src/MediaDock.Api/MediaDock.Api.csproj --configuration Release --no-restore --output /app/api
RUN dotnet publish server/src/MediaDock.Worker/MediaDock.Worker.csproj --configuration Release --no-restore --output /app/worker

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS api
WORKDIR /app
COPY --from=build /app/api/ ./
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
USER $APP_UID
ENTRYPOINT ["dotnet", "MediaDock.Api.dll"]

FROM mcr.microsoft.com/dotnet/runtime:10.0 AS worker
WORKDIR /app
COPY --from=build /app/worker/ ./
USER $APP_UID
ENTRYPOINT ["dotnet", "MediaDock.Worker.dll"]