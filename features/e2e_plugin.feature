Feature: End-to-end mutation testing with pytest-gremlins
  As a developer using pytest
  I want to run mutation testing with --gremlins
  So that I can find gaps in my test coverage

  Background:
    Given a Python project with source code and tests

  @smoke
  Scenario: Running pytest with --gremlins flag enables mutation testing
    When I run "pytest --gremlins"
    Then mutation testing should be enabled
    And gremlins should be generated from the source code
    And tests should be executed for each gremlin
    And a mutation score should be displayed

  Scenario: Mutation testing uses all five operators
    Given source code with comparison, arithmetic, boolean, boundary, and return statements
    When I run "pytest --gremlins"
    Then gremlins should be generated using comparison operator
    And gremlins should be generated using arithmetic operator
    And gremlins should be generated using boolean operator
    And gremlins should be generated using boundary operator
    And gremlins should be generated using return operator

  Scenario: Coverage-guided test selection runs only relevant tests
    Given source code with multiple functions
    And tests that each cover different functions
    When I run "pytest --gremlins"
    Then each gremlin should only run tests that cover its location
    And test execution count should be less than gremlins times total tests

  Scenario: Console report shows mutation score
    When I run "pytest --gremlins"
    Then the output should contain "pytest-gremlins mutation report"
    And the output should show zapped gremlins count
    And the output should show survived gremlins count
    And the output should display mutation score percentage

  Scenario: Surviving gremlins indicate test gaps
    Given source code with a comparison "age >= 18"
    And tests that only check exact boundary value 18
    When I run "pytest --gremlins"
    Then some gremlins should survive
    And the report should list the surviving gremlin locations

  Scenario: Zapped gremlins indicate good test coverage
    Given source code with a comparison "age >= 18"
    And tests that check values 17, 18, and 19
    When I run "pytest --gremlins"
    Then all gremlins for that comparison should be zapped

  Scenario: HTML report generation
    When I run "pytest --gremlins --gremlin-report=html"
    Then an HTML report should be generated
    And the HTML report should contain mutation results by file

  Scenario: JSON report generation
    When I run "pytest --gremlins --gremlin-report=json"
    Then a JSON report should be generated
    And the JSON report should contain structured mutation results

  Scenario: Specifying operators via command line
    When I run "pytest --gremlins --gremlin-operators=comparison,arithmetic"
    Then only comparison and arithmetic operators should be used
    And no boolean, boundary, or return mutations should be generated

  Scenario: Mutation switching via environment variable
    Given source code instrumented with gremlins
    When ACTIVE_GREMLIN environment variable is set to a gremlin ID
    Then the corresponding mutation should be active
    And when ACTIVE_GREMLIN is unset
    Then the original code should execute

  Scenario: No gremlins mode runs tests normally
    When I run "pytest" without the --gremlins flag
    Then mutation testing should not be enabled
    And tests should run as normal
