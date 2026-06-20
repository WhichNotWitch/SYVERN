package org.syvern.pilot;

/**
 * The judgement seam. {@link StubPilotBackend} provides a deterministic
 * placeholder; the H7 deliverable is {@link RealPilotBackend} wrapping the
 * official SysML v2 Pilot Implementation (Xtext/EMF).
 */
public interface PilotBackend {

    /** Parse + resolve + typecheck + element extraction in a single pass. */
    Api.AnalysisResult analyze(String text);

    /** Backend version for the SYVERN fingerprint handshake. */
    Api.Version version();
}
