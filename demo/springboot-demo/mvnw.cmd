@REM ----------------------------------------------------------------------------
@REM Licensed to the Apache Software Foundation (ASF) under one
@REM or more contributor license agreements.  See the NOTICE file
@REM distributed with this work for additional information
@REM regarding copyright ownership.  The ASF licenses this file
@REM to you under the Apache License, Version 2.0 (the
@REM "License"); you may not use this file except in compliance
@REM with the License.  You may obtain a copy of the License at
@REM
@REM    http://www.apache.org/licenses/LICENSE-2.0
@REM
@REM Unless required by applicable law or agreed to in writing,
@REM software distributed under the License is distributed on an
@REM "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
@REM KIND, either express or implied.  See the License for the
@REM specific language governing permissions and limitations
@REM under the License.
@REM ----------------------------------------------------------------------------

@REM ----------------------------------------------------------------------------
@REM Apache Maven Wrapper startup script for Windows
@REM ----------------------------------------------------------------------------

@echo off
@REM set local scope for the variables with windows NT shell
if "%OS%"=="Windows_NT" setlocal

set DIRNAME=%~dp0
if "%DIRNAME%"=="" set DIRNAME=.
@REM This is normally unused
set APP_BASE_NAME=%~n0
set APP_HOME=%DIRNAME%

@REM Resolve any "." and ".." in APP_HOME to make it shorter.
for %%i in ("%APP_HOME%") do set APP_HOME=%%~fi

@REM Add default JVM options here. You can also use JAVA_OPTS and MAVEN_OPTS to pass JVM options to this script.
set DEFAULT_JVM_OPTS="-Xmx64m" "-Xms64m"

@REM Find java.exe
if defined JAVA_HOME goto findJavaFromJavaHome

set JAVA_EXE=java.exe
%JAVA_EXE% -version >NUL 2>&1
if %ERRORLEVEL% equ 0 goto execute

echo. 1>&2
echo ERROR: JAVA_HOME is not set and no 'java' command could be found in your PATH. 1>&2
echo. 1>&2
echo Please set the JAVA_HOME variable in your environment to match the 1>&2
echo location of your Java installation. 1>&2

goto fail

:findJavaFromJavaHome
set JAVA_HOME=%JAVA_HOME:"=%
set JAVA_EXE=%JAVA_HOME%/bin/java.exe

if exist "%JAVA_EXE%" goto execute

echo. 1>&2
echo ERROR: JAVA_HOME is set to an invalid directory: %JAVA_HOME% 1>&2
echo. 1>&2
echo Please set the JAVA_HOME variable in your environment to match the 1>&2
echo location of your Java installation. 1>&2

goto fail

:execute
@REM Setup the command line

set WRAPPER_JAR="%APP_HOME%\.mvn\wrapper\maven-wrapper.jar"
set WRAPPER_PROPERTIES="%APP_HOME%\.mvn\wrapper\maven-wrapper.properties"

@REM Determine the Maven command to use
if exist %WRAPPER_JAR% (
    set WRAPPER_CMD="%JAVA_EXE%" %DEFAULT_JVM_OPTS% %JAVA_OPTS% %MAVEN_OPTS% -classpath %WRAPPER_JAR% "-Dmaven.multiModuleProjectDirectory=%APP_HOME%" org.apache.maven.wrapper.MavenWrapperMain %*
) else (
    @REM Download the wrapper jar if it doesn't exist
    set WRAPPER_URL="https://repo.maven.apache.org/maven2/org/apache/maven/wrapper/maven-wrapper/3.2.0/maven-wrapper-3.2.0.jar"
    powershell -Command "&{"^
		"$webclient = new-object System.Net.WebClient;"^
		"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $webclient.DownloadFile('%WRAPPER_URL%', '%WRAPPER_JAR%')"^
		"}"
    set WRAPPER_CMD="%JAVA_EXE%" %DEFAULT_JVM_OPTS% %JAVA_OPTS% %MAVEN_OPTS% -classpath %WRAPPER_JAR% "-Dmaven.multiModuleProjectDirectory=%APP_HOME%" org.apache.maven.wrapper.MavenWrapperMain %*
)

%WRAPPER_CMD%
if %ERRORLEVEL% equ 0 goto end

:fail
rem Set variable MAVEN_EXIT_CONSOLE if you need the _script_ return code instead of
rem the _cmd.exe /c_ return code!
set EXIT_CODE=%ERRORLEVEL%
if %EXIT_CODE% equ 0 set EXIT_CODE=1
if not ""=="%MAVEN_EXIT_CONSOLE%" exit %EXIT_CODE%
exit /b %EXIT_CODE%

:end
if "%OS%"=="Windows_NT" endlocal

:omega
