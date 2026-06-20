package org.syvern.pilot;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/**
 * Wire DTOs for the SYVERN Pilot service. JSON shape matches
 * doc/syvern_pilot_backend_design.md §3.1. Records are serialized with Gson;
 * snake_case keys are pinned with {@link SerializedName} so the contract does
 * not depend on a field-naming policy.
 */
public final class Api {

    private Api() {
    }

    public record Diagnostic(String code, String message, String location) {
    }

    public record Element(String type, @SerializedName("qualified_name") String qualifiedName) {
    }

    public record ParseStage(boolean ok, List<Diagnostic> errors) {
    }

    public record ResolveStage(
            boolean ok,
            @SerializedName("unresolved_refs") int unresolvedRefs,
            List<Diagnostic> errors) {
    }

    public record TypecheckStage(
            boolean ok,
            @SerializedName("type_errors") int typeErrors,
            List<Diagnostic> errors) {
    }

    public record AnalysisResult(
            ParseStage parse,
            ResolveStage resolve,
            TypecheckStage typecheck,
            List<Element> elements,
            @SerializedName("backend_version") String backendVersion) {
    }

    public record Version(
            @SerializedName("pilot_version") String pilotVersion,
            @SerializedName("grammar_version") String grammarVersion,
            @SerializedName("rules_version") String rulesVersion) {
    }

    public record ValidateRequest(String text) {
    }
}
