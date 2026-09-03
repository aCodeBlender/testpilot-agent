package com.example.demo;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Minimal tests for the Demo API.
 *
 * <p>Test 4 locks the intentional Bug A: POST /users with missing name
 * causes a NullPointerException.  If someone "fixes" the bug, this test
 * will fail, alerting us that the demo target changed.</p>
 */
@SpringBootTest
@AutoConfigureMockMvc
class UserControllerTest {

    @Autowired
    private MockMvc mockMvc;

    // ── Happy path ────────────────────────────────────────────────────────────

    @Test
    void happyPost_returns201() throws Exception {
        mockMvc.perform(post("/users")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"Alice\",\"email\":\"alice@example.com\",\"age\":20}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNumber())
                .andExpect(jsonPath("$.name").value("Alice"))
                .andExpect(jsonPath("$.email").value("alice@example.com"))
                .andExpect(jsonPath("$.age").value(20));
    }

    // ── GET existing ──────────────────────────────────────────────────────────

    @Test
    void getExisting_returns200() throws Exception {
        // Create first
        String response = mockMvc.perform(post("/users")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"name\":\"Bob\",\"email\":\"bob@example.com\",\"age\":25}"))
                .andReturn().getResponse().getContentAsString();

        // Extract ID
        long id = new com.fasterxml.jackson.databind.ObjectMapper()
                .readTree(response).get("id").asLong();

        mockMvc.perform(get("/users/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("Bob"));
    }

    // ── GET missing ───────────────────────────────────────────────────────────

    @Test
    void getMissing_returns404() throws Exception {
        mockMvc.perform(get("/users/99999"))
                .andExpect(status().isNotFound());
    }

    // ── Intentional Bug A ─────────────────────────────────────────────────────

    /**
     * INTENTIONAL BUG FOR TESTPILOT DEMO
     *
     * <p>POST /users with missing name causes a NullPointerException in
     * UserService.create() because {@code dto.getName().length()} is called
     * on a null reference.</p>
     *
     * <p>In a real server, Spring Boot's default error handling converts this
     * to HTTP 500.  MockMvc propagates the exception as a
     * {@link NestedServletException} instead, so we verify the NPE directly.</p>
     *
     * <p>This test LOCKS the bug so that if someone accidentally fixes it,
     * the test fails and we know the demo target changed.</p>
     *
     * <p>TestPilot should detect this: the OpenAPI spec declares {@code name}
     * as required, so TestPilot generates a {@code required_missing body.name}
     * scenario.  The validator expects 4xx but gets 500 → FAIL.</p>
     */
    @Test
    void intentionalBug_missingName_throwsNpe() throws Exception {
        // MockMvc propagates exceptions; in a real server this becomes 500.
        // Spring Boot 3.x uses jakarta.servlet.ServletException
        Exception ex = assertThrows(jakarta.servlet.ServletException.class, () -> {
            mockMvc.perform(post("/users")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"email\":\"no-name@example.com\",\"age\":20}"));
        });

        // Verify the root cause is our intentional NPE
        Throwable cause = ex.getCause();
        if (cause == null) cause = ex;
        assertInstanceOf(NullPointerException.class, cause);
    }

    // ── OpenAPI spec ──────────────────────────────────────────────────────────

    @Test
    void openApiDocsAvailable() throws Exception {
        mockMvc.perform(get("/v3/api-docs"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.openapi").value("3.0.1"))
                .andExpect(jsonPath("$.paths./users").exists())
                .andExpect(jsonPath("$.paths./users/{id}").exists());
    }

    @Test
    void openApiPostUsersNameRequired() throws Exception {
        String json = mockMvc.perform(get("/v3/api-docs"))
                .andReturn().getResponse().getContentAsString();

        com.fasterxml.jackson.databind.JsonNode root =
                new com.fasterxml.jackson.databind.ObjectMapper().readTree(json);

        com.fasterxml.jackson.databind.JsonNode postSchema = root
                .at("/paths/~1users/post/requestBody/content/application~1json/schema");

        // If it's a $ref, resolve it
        if (postSchema.has("$ref")) {
            String ref = postSchema.get("$ref").asText();
            if (ref.startsWith("#/components/schemas/")) {
                String schemaName = ref.replace("#/components/schemas/", "");
                postSchema = root.at("/components/schemas/" + schemaName);
            }
        }

        // Verify name and email are required
        com.fasterxml.jackson.databind.JsonNode required = postSchema.get("required");
        assertNotNull(required, "POST /users schema should have 'required' array");

        boolean nameRequired = false;
        boolean emailRequired = false;
        for (com.fasterxml.jackson.databind.JsonNode r : required) {
            if ("name".equals(r.asText())) nameRequired = true;
            if ("email".equals(r.asText())) emailRequired = true;
        }
        assertTrue(nameRequired, "name should be required in POST /users schema");
        assertTrue(emailRequired, "email should be required in POST /users schema");
    }
}
