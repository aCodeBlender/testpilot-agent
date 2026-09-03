package com.example.demo;

import java.util.List;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller for User CRUD operations.
 */
@RestController
@RequestMapping("/users")
@Tag(name = "Users", description = "User management API")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    // ── POST /users ──────────────────────────────────────────────────────────

    @Operation(summary = "Create a new user", description = "Creates a user and returns the created object with an assigned ID.")
    @ApiResponses({
        @ApiResponse(responseCode = "201", description = "User created successfully",
            content = @Content(schema = @Schema(implementation = UserDto.class))),
        @ApiResponse(responseCode = "400", description = "Invalid input",
            content = @Content),
        @ApiResponse(responseCode = "500", description = "Internal server error",
            content = @Content),
    })
    @PostMapping
    public ResponseEntity<UserDto> createUser(
            @io.swagger.v3.oas.annotations.parameters.RequestBody(
                description = "User to create",
                required = true,
                content = @Content(schema = @Schema(implementation = UserDto.class))
            )
            @org.springframework.web.bind.annotation.RequestBody UserDto body) {
        // Note: No @Valid — intentional for Bug A
        UserDto created = userService.create(body);
        return ResponseEntity.status(HttpStatus.CREATED).body(created);
    }

    // ── GET /users/{id} ──────────────────────────────────────────────────────

    @Operation(summary = "Get user by ID", description = "Returns a single user by their unique identifier.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "User found",
            content = @Content(schema = @Schema(implementation = UserDto.class))),
        @ApiResponse(responseCode = "404", description = "User not found",
            content = @Content),
    })
    @GetMapping("/{id}")
    public ResponseEntity<UserDto> getUserById(
            @Parameter(description = "User ID", required = true, example = "1")
            @PathVariable long id) {
        UserDto user = userService.findById(id);
        if (user == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(user);
    }

    // ── GET /users ───────────────────────────────────────────────────────────

    @Operation(summary = "List all users", description = "Returns a list of users, optionally limited by the limit parameter.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "Successful operation",
            content = @Content(schema = @Schema(implementation = UserDto.class))),
    })
    @GetMapping
    public ResponseEntity<List<UserDto>> listUsers(
            @Parameter(description = "Maximum number of users to return", example = "100",
                schema = @Schema(minimum = "1", maximum = "100"))
            @RequestParam(defaultValue = "100") int limit) {
        return ResponseEntity.ok(userService.findAll(limit));
    }
}
