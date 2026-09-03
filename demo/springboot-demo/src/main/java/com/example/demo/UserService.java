package com.example.demo;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

import org.springframework.stereotype.Service;

/**
 * In-memory user store. Deterministic — IDs are sequential starting from 1.
 */
@Service
public class UserService {

    private final ConcurrentHashMap<Long, UserDto> store = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong(0);

    public UserDto create(UserDto dto) {
        // ─────────────────────────────────────────────────────────────────────
        // INTENTIONAL BUG FOR TESTPILOT DEMO
        //
        // We deliberately call name.length() without a null check.
        // When name is null (missing from request body), this throws
        // NullPointerException, causing Spring to return HTTP 500.
        //
        // The correct behavior would be to validate and return 400.
        // The OpenAPI spec declares name as required, so TestPilot
        // should detect this as a contract violation.
        // ─────────────────────────────────────────────────────────────────────
        int nameLen = dto.getName().length();  // NPE if name is null

        long id = idSequence.incrementAndGet();
        UserDto user = new UserDto(id, dto.getName(), dto.getEmail(), dto.getAge());
        store.put(id, user);
        return user;
    }

    public UserDto findById(long id) {
        return store.get(id);
    }

    public List<UserDto> findAll(int limit) {
        List<UserDto> result = new ArrayList<>();
        int count = 0;
        for (UserDto user : store.values()) {
            if (count >= limit) break;
            result.add(user);
            count++;
        }
        return result;
    }
}
