package org.syvern.pilot;

import com.google.gson.JsonSyntaxException;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.function.Function;

/**
 * Minimal resident HTTP service wrapping a {@link PilotBackend}. Uses the JDK
 * {@code com.sun.net.httpserver} server and a fixed worker pool — no heavy web
 * framework. Routes match doc/syvern_pilot_backend_design.md §3.1, plus the
 * legacy 3-endpoint contract for the current SYVERN PilotAdapter.
 */
public final class PilotServer {

    // Backend is chosen at startup by the PILOT_BACKEND env var: "stub" (default)
    // or "real" (RealPilotBackend, only present when built with -PwithPilot).
    private static final PilotBackend BACKEND = selectBackend();

    private PilotServer() {
    }

    /**
     * Resolve the backend by name. "real" is loaded reflectively so the default
     * build does not need the (Maven-Central-absent) Pilot dependency on the
     * classpath. Build the optional source set with {@code -PwithPilot} and put
     * the Pilot artifact in mavenLocal to enable it.
     */
    static PilotBackend selectBackend() {
        String kind = System.getenv().getOrDefault("PILOT_BACKEND", "stub").trim();
        if (kind.equalsIgnoreCase("real")) {
            try {
                return (PilotBackend) Class.forName("org.syvern.pilot.RealPilotBackend")
                        .getDeclaredConstructor()
                        .newInstance();
            } catch (ReflectiveOperationException e) {
                throw new IllegalStateException(
                        "PILOT_BACKEND=real but RealPilotBackend is unavailable. Build with "
                                + "-PwithPilot and the SysML v2 Pilot Implementation in mavenLocal "
                                + "(see README). Cause: " + e, e);
            }
        }
        return new StubPilotBackend();
    }

    public static void main(String[] args) throws IOException {
        int port = envInt("PILOT_PORT", 8080);
        int threads = envInt("PILOT_THREADS", 8);
        HttpServer server = start(port, threads, BACKEND);
        System.out.printf("SYVERN Pilot server (%s) listening on :%d with %d workers%n",
                BACKEND.getClass().getSimpleName(), server.getAddress().getPort(), threads);
    }

    /**
     * Build, configure, and start a server. Returns the running instance so
     * callers (tests, embedders) can read its bound port and stop it. Pass
     * {@code port = 0} for an ephemeral port.
     */
    public static HttpServer start(int port, int threads, PilotBackend backend) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.setExecutor(Executors.newFixedThreadPool(threads));

        server.createContext("/health", get(ex -> Map.of("status", "ok")));
        server.createContext("/version", get(ex -> backend.version()));
        server.createContext("/validate", post(body -> backend.analyze(textOf(body))));

        // Legacy contract: lets today's PilotAdapter (separate parse/resolve/typecheck
        // calls) talk to this server before the D2 single-call refactor lands.
        server.createContext("/parse", post(body -> {
            Api.AnalysisResult r = backend.analyze(textOf(body));
            return Map.of("ok", r.parse().ok(), "errors", r.parse().errors(), "elements", r.elements());
        }));
        server.createContext("/resolve", post(body -> {
            Api.AnalysisResult r = backend.analyze(textOf(body));
            return Map.of(
                    "ok", r.resolve().ok(),
                    "unresolved_refs", r.resolve().unresolvedRefs(),
                    "errors", r.resolve().errors());
        }));
        server.createContext("/typecheck", post(body -> {
            Api.AnalysisResult r = backend.analyze(textOf(body));
            return Map.of(
                    "ok", r.typecheck().ok(),
                    "type_errors", r.typecheck().typeErrors(),
                    "errors", r.typecheck().errors());
        }));

        server.start();
        return server;
    }

    private static HttpHandler get(Function<HttpExchange, Object> handler) {
        return exchange -> {
            try {
                if (!"GET".equalsIgnoreCase(exchange.getRequestMethod())) {
                    write(exchange, 405, Map.of("error", "method_not_allowed"));
                    return;
                }
                write(exchange, 200, handler.apply(exchange));
            } catch (Exception e) {
                safeWrite(exchange, 500, Map.of("error", String.valueOf(e.getMessage())));
            }
        };
    }

    private static HttpHandler post(Function<String, Object> handler) {
        return exchange -> {
            try {
                if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                    write(exchange, 405, Map.of("error", "method_not_allowed"));
                    return;
                }
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                Object payload;
                try {
                    payload = handler.apply(body);
                } catch (JsonSyntaxException e) {
                    write(exchange, 400, Map.of("error", "invalid_json"));
                    return;
                }
                write(exchange, 200, payload);
            } catch (Exception e) {
                safeWrite(exchange, 500, Map.of("error", String.valueOf(e.getMessage())));
            }
        };
    }

    private static String textOf(String body) {
        Api.ValidateRequest request = Json.GSON.fromJson(body, Api.ValidateRequest.class);
        return (request == null || request.text() == null) ? "" : request.text();
    }

    private static void write(HttpExchange exchange, int status, Object payload) throws IOException {
        byte[] bytes = Json.GSON.toJson(payload).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    private static void safeWrite(HttpExchange exchange, int status, Object payload) {
        try {
            write(exchange, status, payload);
        } catch (IOException ignored) {
            // client gone; nothing more to do
        }
    }

    private static int envInt(String name, int fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : Integer.parseInt(value.trim());
    }
}
