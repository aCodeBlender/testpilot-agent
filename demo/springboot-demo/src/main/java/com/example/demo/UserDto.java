package com.example.demo;

import io.swagger.v3.oas.annotations.media.Schema;

/**
 * User DTO for request and response.
 *
 * <p>Note: {@code @Schema(requiredMode = REQUIRED)} declares the field as
 * required in the generated OpenAPI spec, but we intentionally do NOT use
 * {@code @Valid} / Bean Validation annotations ({@code @NotBlank}, etc.)
 * on the controller parameter.  This plants Bug A: a null {@code name}
 * reaches the service layer and causes a NullPointerException → 500,
 * instead of the expected 400.</p>
 */
@Schema(description = "User object")
public class UserDto {

    @Schema(description = "Unique identifier", example = "1", accessMode = Schema.AccessMode.READ_ONLY)
    private Long id;

    @Schema(description = "User's full name", example = "Alice", requiredMode = Schema.RequiredMode.REQUIRED, minLength = 1)
    private String name;

    @Schema(description = "Email address", example = "alice@example.com", requiredMode = Schema.RequiredMode.REQUIRED, format = "email")
    private String email;

    @Schema(description = "Age in years", example = "20", minimum = "0", maximum = "150")
    private Integer age;

    // --- Constructors ---

    public UserDto() {
    }

    public UserDto(Long id, String name, String email, Integer age) {
        this.id = id;
        this.name = name;
        this.email = email;
        this.age = age;
    }

    // --- Getters & Setters ---

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getEmail() {
        return email;
    }

    public void setEmail(String email) {
        this.email = email;
    }

    public Integer getAge() {
        return age;
    }

    public void setAge(Integer age) {
        this.age = age;
    }
}
