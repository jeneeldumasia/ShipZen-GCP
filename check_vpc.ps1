$vpcId = "vpc-0ee9598150640b952"

Write-Host "--- Security Groups ---"
aws ec2 describe-security-groups --filters Name=vpc-id,Values=$vpcId --query "SecurityGroups[*].[GroupId,GroupName]" --output table

Write-Host "--- Subnets ---"
aws ec2 describe-subnets --filters Name=vpc-id,Values=$vpcId --query "Subnets[*].[SubnetId]" --output table

Write-Host "--- Internet Gateways ---"
aws ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values=$vpcId --query "InternetGateways[*].[InternetGatewayId]" --output table

Write-Host "--- NAT Gateways ---"
aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=$vpcId --query "NatGateways[*].[NatGatewayId,State]" --output table

Write-Host "--- VPC Endpoints ---"
aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=$vpcId --query "VpcEndpoints[*].[VpcEndpointId]" --output table

Write-Host "--- Route Tables ---"
aws ec2 describe-route-tables --filters Name=vpc-id,Values=$vpcId --query "RouteTables[*].[RouteTableId]" --output table

Write-Host "--- Load Balancers ---"
aws elbv2 describe-load-balancers --query "LoadBalancers[?VpcId=='$vpcId'].[LoadBalancerArn,LoadBalancerName]" --output table

Write-Host "--- Target Groups ---"
aws elbv2 describe-target-groups --query "TargetGroups[?VpcId=='$vpcId'].[TargetGroupArn,TargetGroupName]" --output table
