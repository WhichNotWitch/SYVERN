package org.syvern.pilot;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Integration smoke test: starts the server on an ephemeral port and exercises the contract. */
class PilotServerSmokeTest {

    private HttpServer server;
    private HttpClient client;
    private String base;

    @BeforeEach
    void startServer() throws Exception {
        server = PilotServer.start(0, 2, new StubPilotBackend());
        base = "http://127.0.0.1:" + server.getAddress().getPort();
        client = HttpClient.newHttpClient();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void healthReturnsOk() throws Exception {
        HttpResponse<String> response = get("/health");
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("\"status\":\"ok\""));
    }

    @Test
    void versionExposesBackendVersion() throws Exception {
        Api.Version version = Json.GSON.fromJson(get("/version").body(), Api.Version.class);
        assertEquals("stub-0.1.0", version.pilotVersion());
    }

    @Test
    void validateReturnsFullContractForValidText() throws Exception {
        HttpResponse<String> response = post("/validate",
                "{\"text\":\"part vehicle.engine attribute vehicle.mass\"}");
        assertEquals(200, response.statusCode());

        Api.AnalysisResult result = Json.GSON.fromJson(response.body(), Api.AnalysisResult.class);
        assertTrue(result.parse().ok());
        assertTrue(result.resolve().ok());
        assertTrue(result.typecheck().ok());
        assertEquals(2, result.elements().size());
        assertEquals("stub-0.1.0", result.backendVersion());
    }

    @Test
    void validateFlagsSyntaxError() throws Exception {
        Api.AnalysisResult result = Json.GSON.fromJson(
                post("/validate", "{\"text\":\"syntax_error part a\"}").body(),
                Api.AnalysisResult.class);
        assertFalse(result.parse().ok());
        assertEquals("PARSE_SYNTAX_ERROR", result.parse().errors().get(0).code());
        assertTrue(result.elements().isEmpty());
    }

    @Test
    void legacyParseRouteIsCompatible() throws Exception {
        HttpResponse<String> response = post("/parse",
                "{\"text\":\"part vehicle.engine unresolved_ref x\"}");
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("\"qualified_name\":\"vehicle.engine\""));
    }

    @Test
    void malformedJsonReturns400() throws Exception {
        assertEquals(400, post("/validate", "not json").statusCode());
    }

    @Test
    void wrongMethodReturns405() throws Exception {
        assertEquals(405, get("/validate").statusCode());
    }

    private HttpResponse<String> get(String path) throws Exception {
        return client.send(
                HttpRequest.newBuilder(URI.create(base + path)).timeout(Duration.ofSeconds(5)).GET().build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> post(String path, String body) throws Exception {
        return client.send(
                HttpRequest.newBuilder(URI.create(base + path))
                        .timeout(Duration.ofSeconds(5))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(body))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }
}
