export const PULSE_TESTBENCH = `module tb;
  reg src = 0, dst = 0, rst = 1, pulse = 0;
  wire observed;
  integer pulses = 0;
  ibex_pulse_sync dut(src, dst, rst, pulse, observed);
  always #5 src = ~src;
  always #7 dst = ~dst;
  always @(posedge dst) if (observed === 1'b1) pulses = pulses + 1;
  initial begin
    #1 rst = 0;
    #20;
    if (observed !== 1'b0) $fatal(1, "reset output mismatch");
    rst = 1;
    @(negedge src); pulse = 1;
    @(negedge src); pulse = 0;
    #100;
    if (pulses !== 1) $fatal(1, "expected exactly one synchronized pulse");
    $display("SIGNOFF_TEST_PASS");
    $finish;
  end
endmodule
`;
