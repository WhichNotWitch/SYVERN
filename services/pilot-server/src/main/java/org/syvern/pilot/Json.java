package org.syvern.pilot;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

/** Shared Gson instance. {@code serializeNulls} keeps nullable fields (e.g. error location) explicit. */
final class Json {

    static final Gson GSON = new GsonBuilder().serializeNulls().create();

    private Json() {
    }
}
